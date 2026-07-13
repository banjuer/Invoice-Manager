"""Invoice processing service."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.models.invoice import Invoice, OcrResult, LlmResult, ParsingDiff, InvoiceStatus
from app.services.ocr_service import get_ocr_service, get_field_extractor
from app.services.llm_service import get_llm_service
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Separate thread pools for OCR and LLM to maximize throughput
# OCR is CPU-bound (image processing), LLM is I/O-bound (API calls)
# Using separate pools prevents one from blocking the other
_ocr_executor = ThreadPoolExecutor(max_workers=settings.ocr_max_workers)
_llm_executor = ThreadPoolExecutor(max_workers=settings.llm_max_workers)
logger.info(f"Initialized thread pools: OCR={settings.ocr_max_workers}, LLM={settings.llm_max_workers}")

# Fields to compare between OCR and LLM
COMPARABLE_FIELDS = [
    'invoice_number',
    'issue_date',
    'buyer_name',
    'buyer_tax_id',
    'seller_name',
    'seller_tax_id',
    'item_name',
    'total_with_tax',
    'amount',
    'tax_amount',
    'tax_rate',
]

# Fields where LLM result is preferred over OCR when they differ
# e.g. item_name: OCR often misreads characters, LLM has context awareness
LLM_PREFERRED_FIELDS = {'item_name'}


def _reset_extracted_fields(invoice: Invoice) -> None:
    """Reset extracted fields to avoid stale values on reprocess."""
    for field_name in COMPARABLE_FIELDS:
        setattr(invoice, field_name, None)


def _run_ocr(file_data: bytes, file_type: str) -> Tuple[str, float, Dict[str, Any]]:
    """Run OCR processing in a separate thread.

    Args:
        file_data: Raw file bytes
        file_type: File type (pdf, jpg, png, etc.)

    Returns:
        Tuple of (raw_text, confidence, extracted_fields)
    """
    ocr_service = get_ocr_service()
    extractor = get_field_extractor()

    if file_type == 'pdf':
        raw_text, confidence, ocr_lines = ocr_service.process_pdf(file_data)
    else:
        raw_text, confidence, ocr_lines = ocr_service.process_image(file_data)

    ocr_fields = extractor.extract_fields(raw_text, ocr_lines)
    return raw_text, confidence, ocr_fields


def _run_llm_vision(file_data: bytes, file_type: str) -> Dict[str, Any]:
    """Run LLM vision parsing in a separate thread.

    Args:
        file_data: Raw file bytes
        file_type: File type (pdf, jpg, png, etc.)

    Returns:
        Dictionary of extracted fields
    """
    llm_service = get_llm_service()

    if not llm_service.is_available:
        return {}
    if not llm_service.supports_vision() and not settings.llm_force_vision:
        return {}

    # Determine MIME type
    mime_map = {
        'pdf': 'application/pdf',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
    }
    mime_type = mime_map.get(file_type, 'image/png')

    # For PDF, we need to convert first page to image
    if file_type == 'pdf':
        try:
            from pdf2image import convert_from_bytes
            from io import BytesIO

            # Use higher DPI (300) for better text recognition in PDFs
            # Some PDFs have text rendered as graphics which need higher resolution
            images = convert_from_bytes(file_data, dpi=300, first_page=1, last_page=1)
            if images:
                # Convert PIL Image to bytes with high quality
                buffer = BytesIO()
                images[0].save(buffer, format='PNG', optimize=False)
                file_data = buffer.getvalue()
                mime_type = 'image/png'
                logger.info(f"PDF converted to image: {images[0].size[0]}x{images[0].size[1]} pixels, {len(file_data)} bytes")
            else:
                logger.warning("Failed to convert PDF to image for LLM vision")
                return {}
        except Exception as e:
            logger.error(f"PDF to image conversion failed: {e}")
            return {}

    return llm_service.parse_invoice_from_image(file_data, mime_type)


def _run_llm_text(ocr_text: str) -> Dict[str, Any]:
    """Run LLM text-based parsing using OCR output.

    This is the fallback when vision is not supported by the model.
    Sends the OCR raw text to the LLM for structured extraction.

    Args:
        ocr_text: Raw OCR text from the invoice

    Returns:
        Dictionary of extracted fields
    """
    llm_service = get_llm_service()

    if not llm_service.is_available:
        return {}

    return llm_service.parse_invoice_from_text(ocr_text)





def _has_meaningful_fields(fields: Dict[str, Any]) -> bool:
    """Check if parsed fields contain any meaningful values."""
    if not fields:
        return False
    for value in fields.values():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return True
    return False


async def process_invoice(invoice_id: int, db: AsyncSession) -> bool:
    """Process an invoice: run OCR and LLM vision in parallel, then compare results.

    This function runs OCR and LLM vision parsing in parallel for better performance
    and more accurate results. The LLM analyzes the image directly instead of
    relying on OCR text.

    Args:
        invoice_id: ID of the invoice to process
        db: Database session

    Returns:
        True if processing succeeded, False otherwise
    """
    try:
        # Get invoice
        query = select(Invoice).where(Invoice.id == invoice_id)
        result = await db.execute(query)
        invoice = result.scalar_one_or_none()

        if not invoice:
            logger.error(f"Invoice {invoice_id} not found")
            return False

        # Delete existing OCR, LLM, and diff results for reprocessing
        await db.execute(delete(ParsingDiff).where(ParsingDiff.invoice_id == invoice_id))
        await db.execute(delete(LlmResult).where(LlmResult.invoice_id == invoice_id))
        await db.execute(delete(OcrResult).where(OcrResult.invoice_id == invoice_id))
        logger.info(f"Cleared existing processing results for invoice {invoice_id}")

        # Determine LLM strategy: vision or text-based
        # Note: llm_force_vision only affects the actual API call (for models that
        # support vision but aren't in VISION_MODELS), not the strategy decision.
        # Text-only models go straight to text LLM, avoiding failed vision attempts.
        loop = asyncio.get_running_loop()
        llm_service = get_llm_service()
        llm_has_vision = llm_service.is_available and llm_service.supports_vision()

        if llm_has_vision:
            # Run OCR and LLM vision in PARALLEL for best performance
            logger.info(f"Running OCR and LLM vision in parallel for invoice {invoice_id}")
            ocr_task = loop.run_in_executor(
                _ocr_executor, _run_ocr, invoice.file_data, invoice.file_type
            )
            llm_task = loop.run_in_executor(
                _llm_executor, _run_llm_vision, invoice.file_data, invoice.file_type
            )
            ocr_result_data, llm_fields = await asyncio.gather(ocr_task, llm_task)
            raw_text, confidence, ocr_fields = ocr_result_data
            has_llm = _has_meaningful_fields(llm_fields)
            logger.info(f"OCR completed: {len(ocr_fields)} fields, LLM vision: {len(llm_fields)} fields (has_llm={has_llm})")

            # Fallback: vision LLM returned empty → try text LLM
            if not has_llm:
                logger.info(f"Vision LLM empty, trying text-based LLM for invoice {invoice_id}")
                llm_fields = await loop.run_in_executor(
                    _llm_executor, _run_llm_text, raw_text
                )
                has_llm = _has_meaningful_fields(llm_fields)
                logger.info(f"Text LLM completed: {len(llm_fields)} fields (has_llm={has_llm})")
        elif llm_service.is_available:
            # Vision not supported — OCR first, then text LLM (sequential, not parallel)
            logger.info(f"Vision not supported, running OCR then text LLM for invoice {invoice_id}")
            ocr_result_data = await loop.run_in_executor(
                _ocr_executor, _run_ocr, invoice.file_data, invoice.file_type
            )
            raw_text, confidence, ocr_fields = ocr_result_data
            logger.info(f"OCR completed: {len(ocr_fields)} fields extracted")

            llm_fields = await loop.run_in_executor(
                _llm_executor, _run_llm_text, raw_text
            )
            has_llm = _has_meaningful_fields(llm_fields)
            logger.info(f"Text LLM completed: {len(llm_fields)} fields (has_llm={has_llm})")
        else:
            # No LLM configured — OCR only
            logger.info(f"Running OCR only for invoice {invoice_id} (no LLM configured)")
            ocr_result_data = await loop.run_in_executor(
                _ocr_executor, _run_ocr, invoice.file_data, invoice.file_type
            )
            raw_text, confidence, ocr_fields = ocr_result_data
            has_llm = False
            llm_fields = {}
            logger.info(f"OCR completed: {len(ocr_fields)} fields extracted")

        # Save OCR result
        ocr_result = OcrResult(
            invoice_id=invoice_id,
            raw_text=raw_text,
            invoice_number=ocr_fields.get('invoice_number'),
            issue_date=ocr_fields.get('issue_date'),
            buyer_name=ocr_fields.get('buyer_name'),
            buyer_tax_id=ocr_fields.get('buyer_tax_id'),
            seller_name=ocr_fields.get('seller_name'),
            seller_tax_id=ocr_fields.get('seller_tax_id'),
            item_name=ocr_fields.get('item_name'),
            total_with_tax=ocr_fields.get('total_with_tax'),
            amount=ocr_fields.get('amount'),
            tax_amount=ocr_fields.get('tax_amount'),
            tax_rate=ocr_fields.get('tax_rate'),
        )
        db.add(ocr_result)

        # Save LLM result if available
        if has_llm:
            llm_result = LlmResult(
                invoice_id=invoice_id,
                invoice_number=llm_fields.get('invoice_number'),
                issue_date=llm_fields.get('issue_date'),
                buyer_name=llm_fields.get('buyer_name'),
                buyer_tax_id=llm_fields.get('buyer_tax_id'),
                seller_name=llm_fields.get('seller_name'),
                seller_tax_id=llm_fields.get('seller_tax_id'),
                item_name=llm_fields.get('item_name'),
                total_with_tax=llm_fields.get('total_with_tax'),
                amount=llm_fields.get('amount'),
                tax_amount=llm_fields.get('tax_amount'),
                tax_rate=llm_fields.get('tax_rate'),
            )
            db.add(llm_result)
        else:
            logger.info(f"LLM vision not available - invoice {invoice_id} using OCR-only flow")

        # Compare OCR and LLM results, create diffs
        final_fields, diffs = _compare_and_resolve(ocr_fields, llm_fields, has_llm)

        # Clear extracted fields so missing values don't keep stale data
        _reset_extracted_fields(invoice)

        # Save parsing diffs
        for diff in diffs:
            parsing_diff = ParsingDiff(
                invoice_id=invoice_id,
                field_name=diff['field_name'],
                ocr_value=diff['ocr_value'],
                llm_value=diff['llm_value'],
                final_value=diff['final_value'],
                source=diff['source'],
                resolved=0 if diff['needs_review'] else 1,
            )
            db.add(parsing_diff)

        # Update invoice with final data
        _update_invoice_from_fields(invoice, final_fields)

        # Set status based on whether review is needed
        # Check for conflicts in diffs
        has_conflicts = any(d['needs_review'] for d in diffs)

        # Check for missing critical fields (these require review)
        critical_fields = [
            'invoice_number',
            'issue_date',
            'total_with_tax',
            'buyer_name',
            'buyer_tax_id',
            'seller_name',
            'seller_tax_id',
            'item_name',
        ]
        missing_fields = [f for f in critical_fields if not final_fields.get(f)]
        missing_critical = bool(missing_fields)
        if missing_critical:
            logger.warning(f"Invoice {invoice_id} missing critical fields: {missing_fields}")

        needs_review = has_conflicts or missing_critical
        if needs_review:
            invoice.status = InvoiceStatus.REVIEWING
        else:
            invoice.status = InvoiceStatus.CONFIRMED

        await db.commit()
        logger.info(f"Invoice {invoice_id} processed successfully (needs_review={needs_review})")
        return True

    except Exception as e:
        logger.error(f"Failed to process invoice {invoice_id}: {e}")
        await db.rollback()
        return False


def _compare_and_resolve(
    ocr_fields: Dict[str, Any],
    llm_fields: Dict[str, Any],
    has_llm: bool
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Compare OCR and LLM results, resolve differences.

    Args:
        ocr_fields: Fields extracted by OCR
        llm_fields: Fields extracted by LLM
        has_llm: Whether LLM results are available

    Returns:
        Tuple of (final_fields, diffs_list)
    """
    final_fields = {}
    diffs = []

    for field_name in COMPARABLE_FIELDS:
        ocr_value = _normalize_value(ocr_fields.get(field_name))
        llm_value = _normalize_value(llm_fields.get(field_name)) if has_llm else None

        # Determine final value and whether review is needed
        if not has_llm:
            # No LLM available, use OCR value directly
            final_value = ocr_value
            source = 'ocr'
            needs_review = False
        elif _values_are_equal(field_name, ocr_value, llm_value):
            # Values match (including numeric equivalence like 330.00 == 330)
            final_value = ocr_value or llm_value
            source = 'matched'
            needs_review = False
        elif ocr_value and llm_value:
            # Both have values but they differ
            if field_name in LLM_PREFERRED_FIELDS:
                # LLM-preferred fields: trust LLM over OCR (e.g. item_name)
                final_value = llm_value
                source = 'llm'
                needs_review = False
            else:
                # Other fields: needs manual review
                final_value = None  # Leave blank for manual review
                source = 'conflict'
                needs_review = True
        elif llm_value and not ocr_value:
            # LLM found something OCR missed - prefer LLM
            final_value = llm_value
            source = 'llm'
            needs_review = False
        else:
            # OCR found something LLM missed - prefer OCR
            final_value = ocr_value
            source = 'ocr'
            needs_review = False

        final_fields[field_name] = final_value

        # Record diff if there's a discrepancy or both have values
        if has_llm and (ocr_value or llm_value):
            diffs.append({
                'field_name': field_name,
                'ocr_value': ocr_value,
                'llm_value': llm_value,
                'final_value': final_value,
                'source': source,
                'needs_review': needs_review,
            })

    return final_fields, diffs


def _normalize_value(value: Any) -> Optional[str]:
    """Normalize a value to string for comparison."""
    if value is None:
        return None
    value_str = str(value).strip()
    if not value_str:
        return None
    return value_str


# Fields that should be compared as numbers
NUMERIC_FIELDS = ['total_with_tax', 'amount', 'tax_amount']


def _values_are_equal(field_name: str, value1: Optional[str], value2: Optional[str]) -> bool:
    """Compare two values, using numeric comparison for numeric fields.

    Args:
        field_name: Name of the field being compared
        value1: First value (normalized string)
        value2: Second value (normalized string)

    Returns:
        True if values are considered equal
    """
    # If both are None or empty, they're equal
    if not value1 and not value2:
        return True

    # If only one is None/empty, they're not equal
    if not value1 or not value2:
        return False

    # For numeric fields, compare as numbers
    if field_name in NUMERIC_FIELDS:
        try:
            from decimal import Decimal, InvalidOperation
            # Remove any currency symbols and whitespace
            clean1 = value1.replace('¥', '').replace('￥', '').replace(',', '').strip()
            clean2 = value2.replace('¥', '').replace('￥', '').replace(',', '').strip()
            num1 = Decimal(clean1)
            num2 = Decimal(clean2)
            return num1 == num2
        except (InvalidOperation, ValueError):
            # Fall back to string comparison if not valid numbers
            pass

    # Default to string comparison
    return value1 == value2


def _update_invoice_from_fields(invoice: Invoice, fields: dict) -> None:
    """Update invoice fields from extracted data."""
    from datetime import datetime
    from decimal import Decimal

    if fields.get('invoice_number'):
        invoice.invoice_number = fields['invoice_number']

    if fields.get('issue_date'):
        try:
            invoice.issue_date = datetime.strptime(fields['issue_date'], '%Y-%m-%d').date()
        except ValueError:
            pass

    if fields.get('buyer_name'):
        invoice.buyer_name = fields['buyer_name']

    if fields.get('buyer_tax_id'):
        invoice.buyer_tax_id = fields['buyer_tax_id']

    if fields.get('seller_name'):
        invoice.seller_name = fields['seller_name']

    if fields.get('seller_tax_id'):
        invoice.seller_tax_id = fields['seller_tax_id']

    if fields.get('item_name'):
        invoice.item_name = fields['item_name']

    if fields.get('total_with_tax'):
        try:
            invoice.total_with_tax = Decimal(fields['total_with_tax'])
        except (ValueError, TypeError):
            pass

    if fields.get('amount'):
        try:
            invoice.amount = Decimal(fields['amount'])
        except (ValueError, TypeError):
            pass

    if fields.get('tax_amount'):
        try:
            invoice.tax_amount = Decimal(fields['tax_amount'])
        except (ValueError, TypeError):
            pass

    if fields.get('tax_rate'):
        invoice.tax_rate = fields['tax_rate']


async def reprocess_ocr_only(invoice_id: int, db: AsyncSession) -> bool:
    """Re-run OCR only, keep existing LLM results, and re-compare.

    Useful when the OCR result was poor but LLM is already good.
    """
    try:
        query = select(Invoice).where(Invoice.id == invoice_id)
        result = await db.execute(query)
        invoice = result.scalar_one_or_none()
        if not invoice:
            logger.error(f"Invoice {invoice_id} not found")
            return False

        # Delete existing OCR result and diffs (keep LLM result)
        await db.execute(delete(OcrResult).where(OcrResult.invoice_id == invoice_id))
        await db.execute(delete(ParsingDiff).where(ParsingDiff.invoice_id == invoice_id))

        # Run OCR in thread pool
        loop = asyncio.get_running_loop()
        raw_text, confidence, ocr_fields = await loop.run_in_executor(
            _ocr_executor, _run_ocr, invoice.file_data, invoice.file_type
        )

        # Get existing LLM result (if any)
        llm_query = select(LlmResult).where(LlmResult.invoice_id == invoice_id)
        llm_result_row = await db.execute(llm_query)
        llm = llm_result_row.scalar_one_or_none()
        has_llm = llm is not None

        # Build llm_fields dict from existing LLM result
        llm_fields = {}
        if has_llm:
            for f in COMPARABLE_FIELDS:
                val = getattr(llm, f, None)
                if val:
                    llm_fields[f] = val

        # Save new OCR result
        ocr_result = OcrResult(
            invoice_id=invoice_id,
            raw_text=raw_text,
            invoice_number=ocr_fields.get('invoice_number'),
            issue_date=ocr_fields.get('issue_date'),
            buyer_name=ocr_fields.get('buyer_name'),
            buyer_tax_id=ocr_fields.get('buyer_tax_id'),
            seller_name=ocr_fields.get('seller_name'),
            seller_tax_id=ocr_fields.get('seller_tax_id'),
            item_name=ocr_fields.get('item_name'),
            total_with_tax=ocr_fields.get('total_with_tax'),
            amount=ocr_fields.get('amount'),
            tax_amount=ocr_fields.get('tax_amount'),
            tax_rate=ocr_fields.get('tax_rate'),
        )
        db.add(ocr_result)

        logger.info(f"OCR-only reprocess for invoice {invoice_id}: {len(ocr_fields)} fields")

        # Re-compare
        final_fields, diffs = _compare_and_resolve(ocr_fields, llm_fields, has_llm)

        # Save diffs
        for diff in diffs:
            parsing_diff = ParsingDiff(
                invoice_id=invoice_id,
                field_name=diff['field_name'],
                ocr_value=diff['ocr_value'],
                llm_value=diff['llm_value'],
                final_value=diff['final_value'],
                source=diff['source'],
                resolved=0 if diff['needs_review'] else 1,
            )
            db.add(parsing_diff)

        # Update invoice
        _reset_extracted_fields(invoice)
        _update_invoice_from_fields(invoice, final_fields)

        has_conflicts = any(d['needs_review'] for d in diffs)
        critical_fields = [
            'invoice_number', 'issue_date', 'total_with_tax',
            'buyer_name', 'buyer_tax_id', 'seller_name', 'seller_tax_id', 'item_name',
        ]
        missing_fields = [f for f in critical_fields if not final_fields.get(f)]
        needs_review = has_conflicts or bool(missing_fields)
        invoice.status = InvoiceStatus.REVIEWING if needs_review else InvoiceStatus.CONFIRMED

        await db.commit()
        logger.info(f"OCR-only reprocess for invoice {invoice_id} complete (needs_review={needs_review})")
        return True

    except Exception as e:
        logger.error(f"Failed OCR-only reprocess invoice {invoice_id}: {e}")
        await db.rollback()
        return False


async def reprocess_llm_only(invoice_id: int, db: AsyncSession) -> bool:
    """Re-run LLM only, keep existing OCR results, and re-compare.

    Useful when LLM was misconfigured or not available on first pass.
    """
    try:
        query = select(Invoice).where(Invoice.id == invoice_id)
        result = await db.execute(query)
        invoice = result.scalar_one_or_none()
        if not invoice:
            logger.error(f"Invoice {invoice_id} not found")
            return False

        # Delete existing LLM result and diffs (keep OCR result)
        await db.execute(delete(LlmResult).where(LlmResult.invoice_id == invoice_id))
        await db.execute(delete(ParsingDiff).where(ParsingDiff.invoice_id == invoice_id))

        # Get existing OCR result
        ocr_query = select(OcrResult).where(OcrResult.invoice_id == invoice_id)
        ocr_result_row = await db.execute(ocr_query)
        ocr = ocr_result_row.scalar_one_or_none()

        # Build ocr_fields dict from existing OCR result
        ocr_fields = {}
        if ocr:
            for f in COMPARABLE_FIELDS:
                val = getattr(ocr, f, None)
                if val:
                    ocr_fields[f] = val

        # Run LLM in thread pool — smart strategy: supports_vision() decides
        loop = asyncio.get_running_loop()
        llm_service = get_llm_service()
        llm_has_vision = llm_service.is_available and llm_service.supports_vision()

        if llm_has_vision:
            logger.info(f"Running LLM vision for invoice {invoice_id}")
            llm_fields = await loop.run_in_executor(
                _llm_executor, _run_llm_vision, invoice.file_data, invoice.file_type
            )
            has_llm = _has_meaningful_fields(llm_fields)

            # Fallback: vision LLM empty → try text LLM
            if not has_llm and ocr:
                logger.info(f"Vision LLM empty in reprocess, trying text-based LLM for invoice {invoice_id}")
                llm_fields = await loop.run_in_executor(
                    _llm_executor, _run_llm_text, ocr.raw_text
                )
                has_llm = _has_meaningful_fields(llm_fields)
                logger.info(f"Text LLM in reprocess: {len(llm_fields)} fields (has_llm={has_llm})")
        elif llm_service.is_available and ocr:
            # Vision not supported — use text LLM directly
            logger.info(f"Vision not supported, running text LLM for invoice {invoice_id}")
            llm_fields = await loop.run_in_executor(
                _llm_executor, _run_llm_text, ocr.raw_text
            )
            has_llm = _has_meaningful_fields(llm_fields)
            logger.info(f"Text LLM in reprocess: {len(llm_fields)} fields (has_llm={has_llm})")
        else:
            logger.warning(f"No LLM available or no OCR data for invoice {invoice_id}")
            llm_fields = {}
            has_llm = False

        # Save LLM result if available
        if has_llm:
            llm_result = LlmResult(
                invoice_id=invoice_id,
                invoice_number=llm_fields.get('invoice_number'),
                issue_date=llm_fields.get('issue_date'),
                buyer_name=llm_fields.get('buyer_name'),
                buyer_tax_id=llm_fields.get('buyer_tax_id'),
                seller_name=llm_fields.get('seller_name'),
                seller_tax_id=llm_fields.get('seller_tax_id'),
                item_name=llm_fields.get('item_name'),
                total_with_tax=llm_fields.get('total_with_tax'),
                amount=llm_fields.get('amount'),
                tax_amount=llm_fields.get('tax_amount'),
                tax_rate=llm_fields.get('tax_rate'),
            )
            db.add(llm_result)
        else:
            logger.info(f"LLM-only reprocess for invoice {invoice_id}: LLM returned no meaningful fields")

        # Re-compare
        final_fields, diffs = _compare_and_resolve(ocr_fields, llm_fields, has_llm)

        # Save diffs
        for diff in diffs:
            parsing_diff = ParsingDiff(
                invoice_id=invoice_id,
                field_name=diff['field_name'],
                ocr_value=diff['ocr_value'],
                llm_value=diff['llm_value'],
                final_value=diff['final_value'],
                source=diff['source'],
                resolved=0 if diff['needs_review'] else 1,
            )
            db.add(parsing_diff)

        # Update invoice
        _reset_extracted_fields(invoice)
        _update_invoice_from_fields(invoice, final_fields)

        has_conflicts = any(d['needs_review'] for d in diffs)
        critical_fields = [
            'invoice_number', 'issue_date', 'total_with_tax',
            'buyer_name', 'buyer_tax_id', 'seller_name', 'seller_tax_id', 'item_name',
        ]
        missing_fields = [f for f in critical_fields if not final_fields.get(f)]
        needs_review = has_conflicts or bool(missing_fields)
        invoice.status = InvoiceStatus.REVIEWING if needs_review else InvoiceStatus.CONFIRMED

        await db.commit()
        logger.info(f"LLM-only reprocess for invoice {invoice_id} complete (needs_review={needs_review})")
        return True

    except Exception as e:
        logger.error(f"Failed LLM-only reprocess invoice {invoice_id}: {e}")
        await db.rollback()
        return False


def check_llm_available() -> bool:
    """Check if LLM service is available."""
    return get_llm_service().is_available
