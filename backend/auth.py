"""
Authentication middleware and dependency for NIKOLA backend.
"""
import hashlib
import hmac

from fastapi import Header, HTTPException, Request
from backend.config import settings
from backend.logger import get_logger


logger = get_logger(__name__)


def _fingerprint(value: str | None) -> tuple[int, str | None]:
    if not value:
        return 0, None
    return len(value), hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


async def require_api_key(request: Request, x_api_key: str = Header(None)):
    """Verify X-API-Key header matches configured NIKOLA_API_KEY."""
    if request.url.path in {"/health", "/ready"}:
        return x_api_key
    expected_key = settings.NIKOLA_API_KEY
    if not expected_key:
        raise HTTPException(status_code=503, detail="API key is not configured")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected_key):
        expected_length, expected_fingerprint = _fingerprint(expected_key)
        received_length, received_fingerprint = _fingerprint(x_api_key)
        logger.warning(
            "API key rejected",
            expected_source="backend settings (.env/process environment)",
            expected_length=expected_length,
            expected_sha256_prefix=expected_fingerprint,
            received_length=received_length,
            received_sha256_prefix=received_fingerprint,
        )
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
