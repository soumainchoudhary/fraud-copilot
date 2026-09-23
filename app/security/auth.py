"""API Key Authentication with constant-time comparison."""
import secrets
from typing import Optional

import structlog
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import get_settings

logger = structlog.get_logger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(
    provided_key: Optional[str] = Security(api_key_header),
) -> Optional[str]:
    """Verify incoming X-API-Key against configured secret using constant-time comparison.

    If settings.api_key is empty/not configured, access is granted with an audit warning (dev mode).
    If settings.api_key is set, requests without a valid matching key are rejected with 401.
    """
    settings = get_settings()
    configured_key = settings.api_key.strip()

    # If no API key is configured, pass through (dev mode)
    if not configured_key:
        return None

    if not provided_key:
        logger.warning("auth_failed_missing_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a valid 'X-API-Key' header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(provided_key.strip(), configured_key):
        logger.warning("auth_failed_invalid_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key provided.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return provided_key
