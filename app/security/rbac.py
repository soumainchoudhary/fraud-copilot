"""Role-Based Access Control (RBAC) with granular privilege enforcement."""
from __future__ import annotations

from enum import Enum
from typing import Callable, Optional

import structlog
from fastapi import Header, HTTPException, Request, Security, status

from app.config import get_settings

logger = structlog.get_logger(__name__)


class UserRole(str, Enum):
    """Enterprise security roles."""
    ANALYST_L1 = "ANALYST_L1"
    INVESTIGATOR_L2 = "INVESTIGATOR_L2"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    ADMIN = "ADMIN"


# Role hierarchy weights
ROLE_HIERARCHY: dict[str, int] = {
    UserRole.ANALYST_L1: 10,
    UserRole.INVESTIGATOR_L2: 20,
    UserRole.COMPLIANCE_OFFICER: 30,
    UserRole.ADMIN: 40,
}


def get_current_role(
    request: Request,
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
) -> str:
    """Extract and validate the caller's role from headers or environment context.

    In zero-config dev mode (when API_KEY is not configured and no header is given),
    defaults gracefully to ADMIN to preserve seamless developer ergonomics.
    """
    settings = get_settings()

    if x_user_role:
        role_normalized = x_user_role.strip().upper()
        # Verify valid role name
        valid_roles = {r.value for r in UserRole}
        if role_normalized in valid_roles:
            return role_normalized
        logger.warning("invalid_role_header_rejected", role=x_user_role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Invalid security role '{x_user_role}'. Allowed: {sorted(valid_roles)}",
        )

    # In dev mode when API key is not required, default to ADMIN
    if not settings.api_key:
        return UserRole.ADMIN.value

    # If API key is configured but no explicit role is passed, default to ANALYST_L1
    return UserRole.ANALYST_L1.value


def require_role(*allowed_roles: UserRole | str) -> Callable:
    """FastAPI endpoint dependency ensuring caller has one of the specified roles or higher."""
    allowed_str_roles = {r.value if isinstance(r, UserRole) else str(r).upper() for r in allowed_roles}

    def role_dependency(role: str = Security(get_current_role)) -> str:
        # Check explicit membership or ADMIN override
        if role == UserRole.ADMIN.value or role in allowed_str_roles:
            return role

        logger.warning(
            "rbac_access_denied",
            user_role=role,
            required_roles=list(allowed_str_roles),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Insufficient privileges. Required role in {sorted(list(allowed_str_roles))}, your role: '{role}'",
        )

    return role_dependency
