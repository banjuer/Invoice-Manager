"""Rate limiting configuration for the API.

Rate limiting is disabled by default (suitable for private deployment).
Enable via ENABLE_RATE_LIMIT=true in .env if needed.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Global rate limiter instance
# Default: 100 requests per minute per IP (effective only when enabled)
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
limiter._enabled = False  # Disabled by default for private/internal deployments
