"""
Authentication middleware and dependency for NIKOLA backend.
"""
import os
from fastapi import Header, HTTPException, Request
from backend.config import settings


async def require_api_key(request: Request, x_api_key: str = Header(None)):
    """Verify X-API-Key header matches configured NIKOLA_API_KEY."""
    if request.url.path in {"/health", "/ready"}:
        return x_api_key
    expected_key = os.environ.get("NIKOLA_API_KEY", settings.NIKOLA_API_KEY)
    if not expected_key:
        raise HTTPException(status_code=503, detail="API key is not configured")
    if x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
