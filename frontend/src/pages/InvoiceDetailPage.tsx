import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Descriptions,
  Button,
  message,
  Spin,
  Row,
  Col,
  Form,
  Input,
  Select,
  Modal,
} from 'antd';
import {
  ArrowLeftOutlined,
  EditOutlined,
  SaveOutlined,
  SyncOutlined,
  ScanOutlined,
  RobotOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import { getInvoice, getInvoiceByNumber, getInvoiceFileUrl, getInvoiceFilePreviewUrl, updateInvoice, resolveDiff, confirmInvoice, reprocessInvoice, reprocessOcr, reprocessLlm } from '../services/api';
import type { InvoiceDetail } from '../types/invoice';
import { InvoiceStatus } from '../types/invoice';
import StatusTag from '../components/StatusTag';
import styles from './InvoiceDetailPage.module.css';

const fieldLabels: Record<string, string> = {
  invoice_number: '发票号码',
  issue_date: '开票日期',
  buyer_name: '购买方名称',
  buyer_tax_id: '购买方纳税人识别号',
  seller_name: '销售方名称',
  seller_tax_id: '销售方纳税人识别号',
  item_name: '项目名称',
  total_with_tax: '价税合计',
  specification: '规格型号',
  unit: '单位',
  quantity: '数量',
  unit_price: '单价',
  amount: '金额',
  tax_rate: '税率',
  tax_amount: '税额',
};

function InvoiceDetailPage() {
  const { id, number } = useParams<{ id?: string; number?: string }>();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [reprocessing, setReprocessing] = useState(false);
  const [reprocessingOcr, setReprocessingOcr] = useState(false);
  const [reprocessingLlm, setReprocessingLlm] = useState(false);
  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [form] = Form.useForm();
  const [resolvingDiff, setResolvingDiff] = useState<number | null>(null);
  const [customValueModal, setCustomValueModal] = useState<{ visible: boolean; diffId: number | null; fieldName: string }>({
    visible: false,
    diffId: null,
    fieldName: '',
  });
  const [customValue, setCustomValue] = useState('');

  const fetchInvoice = async () => {
    setLoading(true);
    try {
      let data: InvoiceDetail;
      if (number) {
        // Open by invoice number
        data = await getInvoiceByNumber(number);
      } else if (id) {
        // Open by database ID
        data = await getInvoice(parseInt(id));
      } else {
        return;
      }
      setInvoice(data);
      form.setFieldsValue(data);
    } catch (error) {
      message.error('获取发票详情失败');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchInvoice();
  }, [id, number]);

  const handleSave = async () => {
    if (!id || !invoice) return;

    try {
      const values = await form.validateFields();
      await updateInvoice(parseInt(id), values);
      message.success('保存成功');
      setEditMode(false);
      fetchInvoice();
    } catch (error) {
      message.error('保存失败');
    }
  };

  const handleResolveDiff = async (diffId: number, source: 'ocr' | 'llm' | 'custom', customVal?: string) => {
    if (!id) return;
    setResolvingDiff(diffId);
    try {
      const result = await resolveDiff(parseInt(id), diffId, source, customVal);
      message.success(`${fieldLabels[result.field_name] || result.field_name} 已解决`);
      if (result.all_resolved) {
        message.success('所有差异已解决，发票已确认');
      }
      fetchInvoice();
    } catch (error) {
      message.error('解决差异失败');
    } finally {
      setResolvingDiff(null);
    }
  };

  const handleConfirmAll = async () => {
    if (!id) return;

    if (invoice) {
      const requiredFields: Array<keyof InvoiceDetail> = [
        'invoice_number',
        'issue_date',
        'total_with_tax',
        'buyer_name',
        'buyer_tax_id',
        'seller_name',
        'seller_tax_id',
        'item_name',
      ];
      const missing = requiredFields.filter((field) => {
        const value = invoice[field];
        if (value === null || value === undefined) {
          return true;
        }
        if (typeof value === 'string') {
          return value.trim().length === 0;
        }
        return false;
      });

      if (missing.length > 0) {
        message.error('请先补全必填字段，再进行确认。');
        return;
      }
    }

    try {
      await confirmInvoice(parseInt(id));
      message.success(invoice?.llm_result ? '发票已确认' : '发票已确认（OCR-only）');
      fetchInvoice();
    } catch (error: unknown) {
      if (error && typeof error === 'object' && 'response' in error) {
        const axiosError = error as { response?: { data?: { detail?: string } } };
        if (axiosError.response?.data?.detail) {
          message.error(axiosError.response.data.detail);
          return;
        }
      }
      message.error('确认失败');
    }
  };

  const handleReprocess = async () => {
    if (!id) return;
    setReprocessing(true);
    try {
      await reprocessInvoice(parseInt(id));
      message.success('重新解析完成');
      await fetchInvoice();
    } catch (error) {
      message.error('重新解析失败');
    } finally {
      setReprocessing(false);
    }
  };

  const handleReprocessOcr = async () => {
    if (!id) return;
    setReprocessingOcr(true);
    try {
      await reprocessOcr(parseInt(id));
      message.success('OCR 重新解析完成');
      await fetchInvoice();
    } catch (error) {
      message.error('OCR 重新解析失败');
    } finally {
      setReprocessingOcr(false);
    }
  };

  const handleReprocessLlm = async () => {
    if (!id) return;
    setReprocessingLlm(true);
    try {
      await reprocessLlm(parseInt(id));
      message.success('LLM 重新解析完成');
      await fetchInvoice();
    } catch (error) {
      message.error('LLM 重新解析失败');
    } finally {
      setReprocessingLlm(false);
    }
  };

  /** 根据 source 返回来源标签的显示文本和颜色样式 */
  const getSourceTag = (fieldName: string): { text: string; color: string } | null => {
    if (!invoice?.field_sources) return null;
    const source = invoice.field_sources[fieldName];
    if (!source) return null;
    const map: Record<string, { text: string; color: string }> = {
      ocr: { text: 'OCR', color: '#3b82f6' },
      llm: { text: 'LLM', color: '#8b5cf6' },
      matched: { text: 'OCR+LLM', color: '#10b981' },
      conflict: { text: '冲突', color: '#ef4444' },
      manual: { text: '人工', color: '#6b7280' },
      custom: { text: '自定义', color: '#f59e0b' },
    };
    return map[source] || null;
  };

  const handleCustomValueSubmit = async () => {
    if (customValueModal.diffId) {
      await handleResolveDiff(customValueModal.diffId, 'custom', customValue);
      setCustomValueModal({ visible: false, diffId: null, fieldName: '' });
      setCustomValue('');
    }
  };

  if (loading) {
    return (
      <div className={styles.loadingContainer}>
        <Spin size="large" />
      </div>
    );
  }

  if (!invoice) {
    return <div>发票不存在</div>;
  }

  const hasLlm = Boolean(invoice.llm_result);
  const hasDiffs = Boolean(invoice.parsing_diffs && invoice.parsing_diffs.length > 0);
  const hasUnresolvedDiffs = Boolean(invoice.parsing_diffs && invoice.parsing_diffs.some(d => !d.resolved));

  // Calculate match count for comparison header
  const matchCount = invoice.parsing_diffs?.filter(d => d.resolved).length || 0;
  const totalCount = invoice.parsing_diffs?.length || 0;

  return (
    <div className={styles.pageContainer}>
      {/* Page Header */}
      <div className={styles.pageHeader}>
        <div className={styles.headerLeft}>
          {/* Back button removed: all detail views are now standalone (no sidebar) */}
          <div className={styles.headerTitle}>
            <div className={styles.invoiceNumber}>
              {invoice.invoice_number || '发票详情'}
            </div>
            <div className={styles.invoiceMetadata}>
              开票日期: {invoice.issue_date || '-'} • 归属: {invoice.owner || '-'}
            </div>
          </div>
        </div>
        <div className={styles.headerActions}>
          <button className={styles.rejectButton} disabled title="功能开发中">
            拒绝
          </button>
          <button className={styles.confirmButton} onClick={handleConfirmAll}>
            确认发票
          </button>
        </div>
      </div>

      {/* Content Body */}
      <div className={styles.contentBody}>
        {/* Left Panel */}
        <div className={styles.leftPanel}>
          {/* Invoice Info Card */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div className={styles.cardTitle}>
                发票信息
                <StatusTag status={invoice.status === '已确认' ? 'success' : 'processing'}>
                  {invoice.status}
                </StatusTag>
              </div>
              <div className={styles.cardActions}>
                {editMode ? (
                  <>
                    <Button onClick={() => setEditMode(false)}>取消</Button>
                    <Button type="primary" icon={<SaveOutlined />} onClick={handleSave}>
                      保存
                    </Button>
                  </>
                ) : (
                  <Button icon={<EditOutlined />} onClick={() => setEditMode(true)}>
                    编辑
                  </Button>
                )}
              </div>
            </div>
            <div className={styles.cardBody}>
              {editMode ? (
                <Form form={form} layout="vertical">
                  <Row gutter={16}>
                    <Col span={12}>
                      <Form.Item name="invoice_number" label="发票号码">
                        <Input />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="issue_date" label="开票日期">
                        <Input />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="buyer_name" label="购买方名称">
                        <Input />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="buyer_tax_id" label="购买方纳税人识别号">
                        <Input />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="seller_name" label="销售方名称">
                        <Input />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="seller_tax_id" label="销售方纳税人识别号">
                        <Input />
                      </Form.Item>
                    </Col>
                    <Col span={24}>
                      <Form.Item name="item_name" label="项目名称">
                        <Input />
                      </Form.Item>
                    </Col>
                    <Col span={8}>
                      <Form.Item name="total_with_tax" label="价税合计">
                        <Input type="number" />
                      </Form.Item>
                    </Col>
                    <Col span={8}>
                      <Form.Item name="amount" label="金额">
                        <Input type="number" />
                      </Form.Item>
                    </Col>
                    <Col span={8}>
                      <Form.Item name="tax_amount" label="税额">
                        <Input type="number" />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="status" label="状态">
                        <Select
                          options={Object.values(InvoiceStatus).map((s) => ({
                            label: s,
                            value: s,
                          }))}
                        />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="owner" label="归属人">
                        <Input />
                      </Form.Item>
                    </Col>
                  </Row>
                </Form>
              ) : (
                <>
                {(() => {
                  const fields: Array<{ key: string; label: string; value: React.ReactNode; span?: number }> = [];
                  const s = (k: string) => getSourceTag(k);
                  fields.push({ key: 'invoice_number', label: '发票号码', value: <>{invoice.invoice_number || '-'}{s('invoice_number') && <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 4, background: s('invoice_number')!.color + '18', color: s('invoice_number')!.color, fontWeight: 600 }}>{s('invoice_number')!.text}</span>}</> });
                  fields.push({ key: 'issue_date', label: '开票日期', value: <>{invoice.issue_date || '-'}{s('issue_date') && <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 4, background: s('issue_date')!.color + '18', color: s('issue_date')!.color, fontWeight: 600 }}>{s('issue_date')!.text}</span>}</> });
                  fields.push({ key: 'buyer_name', label: '购买方名称', value: <>{invoice.buyer_name || '-'}{s('buyer_name') && <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 4, background: s('buyer_name')!.color + '18', color: s('buyer_name')!.color, fontWeight: 600 }}>{s('buyer_name')!.text}</span>}</> });
                  fields.push({ key: 'buyer_tax_id', label: '购买方纳税人识别号', value: <>{invoice.buyer_tax_id || '-'}{s('buyer_tax_id') && <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 4, background: s('buyer_tax_id')!.color + '18', color: s('buyer_tax_id')!.color, fontWeight: 600 }}>{s('buyer_tax_id')!.text}</span>}</> });
                  fields.push({ key: 'seller_name', label: '销售方名称', value: <>{invoice.seller_name || '-'}{s('seller_name') && <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 4, background: s('seller_name')!.color + '18', color: s('seller_name')!.color, fontWeight: 600 }}>{s('seller_name')!.text}</span>}</> });
                  fields.push({ key: 'seller_tax_id', label: '销售方纳税人识别号', value: <>{invoice.seller_tax_id || '-'}{s('seller_tax_id') && <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 4, background: s('seller_tax_id')!.color + '18', color: s('seller_tax_id')!.color, fontWeight: 600 }}>{s('seller_tax_id')!.text}</span>}</> });
                  fields.push({ key: 'item_name', label: '项目名称', span: 2, value: <>{invoice.item_name || '-'}{s('item_name') && <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 4, background: s('item_name')!.color + '18', color: s('item_name')!.color, fontWeight: 600 }}>{s('item_name')!.text}</span>}</> });
                  fields.push({ key: 'amount', label: '金额', value: <>{invoice.amount != null ? `¥${Number(invoice.amount).toFixed(2)}` : '-'}{s('amount') && <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 4, background: s('amount')!.color + '18', color: s('amount')!.color, fontWeight: 600 }}>{s('amount')!.text}</span>}</> });
                  fields.push({ key: 'tax_rate', label: '税率', value: <>{invoice.tax_rate || '-'}{s('tax_rate') && <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 4, background: s('tax_rate')!.color + '18', color: s('tax_rate')!.color, fontWeight: 600 }}>{s('tax_rate')!.text}</span>}</> });
                  fields.push({ key: 'tax_amount', label: '税额', value: <>{invoice.tax_amount != null ? `¥${Number(invoice.tax_amount).toFixed(2)}` : '-'}{s('tax_amount') && <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 4, background: s('tax_amount')!.color + '18', color: s('tax_amount')!.color, fontWeight: 600 }}>{s('tax_amount')!.text}</span>}</> });
                  fields.push({ key: 'total_with_tax', label: '价税合计', value: <>{invoice.total_with_tax != null ? `¥${Number(invoice.total_with_tax).toFixed(2)}` : '-'}{s('total_with_tax') && <span style={{ marginLeft: 8, fontSize: 11, padding: '1px 6px', borderRadius: 4, background: s('total_with_tax')!.color + '18', color: s('total_with_tax')!.color, fontWeight: 600 }}>{s('total_with_tax')!.text}</span>}</> });
                  fields.push({ key: 'owner', label: '归属人', value: invoice.owner || '-' });
                  return (
                    <Descriptions column={2} bordered size="small">
                      {fields.map(f => (
                        <Descriptions.Item key={f.key} label={f.label} span={f.span || 1}>
                          {f.value}
                        </Descriptions.Item>
                      ))}
                    </Descriptions>
                  );
                })()}
                </>
              )}
            </div>
          </div>

          {/* Comparison & Review Section */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div className={styles.cardTitle}>
                解析结果比对
                {!hasLlm && (
                  <StatusTag status="processing">
                    OCR-only
                  </StatusTag>
                )}
                {hasLlm && hasUnresolvedDiffs && (
                  <StatusTag status="warning">
                    {totalCount - matchCount}/{totalCount} 待确认
                  </StatusTag>
                )}
                {hasLlm && hasDiffs && !hasUnresolvedDiffs && (
                  <StatusTag status="success">
                    已完成比对
                  </StatusTag>
                )}
              </div>
              <div className={styles.cardActions}>
                <Button
                  icon={<ScanOutlined spin={reprocessingOcr} />}
                  onClick={handleReprocessOcr}
                  loading={reprocessingOcr}
                  size="small"
                >
                  重新OCR
                </Button>
                <Button
                  icon={<RobotOutlined spin={reprocessingLlm} />}
                  onClick={handleReprocessLlm}
                  loading={reprocessingLlm}
                  size="small"
                >
                  重新LLM
                </Button>
                <Button
                  icon={<SyncOutlined spin={reprocessing} />}
                  onClick={handleReprocess}
                  loading={reprocessing}
                  size="small"
                >
                  全部重解析
                </Button>
              </div>
            </div>

            <Spin spinning={reprocessing || reprocessingOcr || reprocessingLlm} tip="正在重新解析...">
              {hasLlm && hasDiffs && (
                <div className={styles.comparisonHeader}>
                  <span className={styles.matchStatus}>
                    {matchCount}/{totalCount} 字段匹配
                  </span>
                </div>
              )}

              <div className={styles.cardBody}>
              {!hasLlm && (
                <div className={styles.infoAlert}>
                  发票已通过OCR识别预处理，可直接编辑后确认。配置LLM服务可获得更精准的智能比对功能，点击"重新解析"启用双重校验。
                </div>
              )}
              {hasDiffs ? (
                <table className={styles.comparisonTable}>
                  <thead>
                    <tr>
                      <th style={{ width: '20%' }}>字段</th>
                      <th style={{ width: '30%' }}>OCR识别结果</th>
                      <th style={{ width: '30%' }}>LLM解析结果</th>
                      <th style={{ width: '20%' }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoice.parsing_diffs?.map((diff) => {
                      const isMatch = diff.ocr_value === diff.llm_value;
                      return (
                        <tr key={diff.id} className={!isMatch ? styles.mismatch : styles.match}>
                          <td className={styles.fieldCell}>
                            {fieldLabels[diff.field_name] || diff.field_name}
                          </td>
                          <td>
                            <div className={styles.valueCell}>
                              {!isMatch && <CloseCircleOutlined className={`${styles.statusIcon} ${styles.mismatch}`} />}
                              {isMatch && <CheckCircleOutlined className={`${styles.statusIcon} ${styles.match}`} />}
                              <span>{diff.ocr_value || '-'}</span>
                            </div>
                          </td>
                          <td>
                            <div className={styles.valueCell}>
                              {!isMatch && <CloseCircleOutlined className={`${styles.statusIcon} ${styles.mismatch}`} />}
                              {isMatch && <CheckCircleOutlined className={`${styles.statusIcon} ${styles.match}`} />}
                              <span>{diff.llm_value || '-'}</span>
                            </div>
                          </td>
                          <td>
                            {!diff.resolved && !isMatch && (
                              <div style={{ display: 'flex', gap: '8px' }}>
                                <Button
                                  type="link"
                                  size="small"
                                  loading={resolvingDiff === diff.id}
                                  onClick={() => handleResolveDiff(diff.id, 'ocr')}
                                >
                                  选OCR
                                </Button>
                                <Button
                                  type="link"
                                  size="small"
                                  loading={resolvingDiff === diff.id}
                                  onClick={() => handleResolveDiff(diff.id, 'llm')}
                                >
                                  选LLM
                                </Button>
                                <Button
                                  type="link"
                                  size="small"
                                  onClick={() => {
                                    setCustomValueModal({ visible: true, diffId: diff.id, fieldName: diff.field_name });
                                    setCustomValue(diff.ocr_value || diff.llm_value || '');
                                  }}
                                >
                                  自定义
                                </Button>
                              </div>
                            )}
                            {diff.resolved && (
                              <StatusTag status="success">已解决</StatusTag>
                            )}
                            {isMatch && !diff.resolved && (
                              <Button
                                type="link"
                                size="small"
                                onClick={() => handleResolveDiff(diff.id, 'ocr')}
                              >
                                确认
                              </Button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              ) : (
                <div style={{ textAlign: 'center', padding: '20px', color: '#999' }}>
                  {hasLlm ? '无比对差异' : 'OCR-only 模式暂无比对数据'}
                </div>
              )}
            </div>
            </Spin>
          </div>

          {/* Custom Value Modal */}
          <Modal
            title={`自定义值 - ${fieldLabels[customValueModal.fieldName] || customValueModal.fieldName}`}
            open={customValueModal.visible}
            onOk={handleCustomValueSubmit}
            onCancel={() => {
              setCustomValueModal({ visible: false, diffId: null, fieldName: '' });
              setCustomValue('');
            }}
            okText="确定"
            cancelText="取消"
          >
            <Input
              value={customValue}
              onChange={(e) => setCustomValue(e.target.value)}
              placeholder="请输入自定义值"
            />
          </Modal>
        </div>

        {/* Right Panel - PDF Preview */}
        <div className={styles.rightPanel}>
          <div className={styles.previewCard}>
            <div className={styles.previewHeader}>
              <span className={styles.previewTitle}>原始文件</span>
              <div className={styles.previewControls}>
                <a
                  href={getInvoiceFileUrl(invoice.id)}
                  download
                  className={styles.downloadButton}
                >
                  <DownloadOutlined />
                  下载
                </a>
              </div>
            </div>
            <div className={styles.previewBody}>
              <div className={styles.previewContent}>
                {invoice.file_type === 'pdf' ? (
                  <iframe
                    src={getInvoiceFilePreviewUrl(invoice.id)}
                    style={{ width: '100%', height: 600, border: 'none' }}
                    title="PDF Preview"
                  />
                ) : (
                  <img
                    src={getInvoiceFilePreviewUrl(invoice.id)}
                    alt="Invoice"
                    style={{ width: '100%', maxHeight: 600, objectFit: 'contain' }}
                  />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default InvoiceDetailPage;
