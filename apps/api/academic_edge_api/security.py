"""Authentication and role checks.

An ``X-API-Key`` header is mapped to ``reader < analyst < admin`` through the
``API_KEYS`` setting (``key:role`` pairs). When no keys are configured the
service runs in an explicit **dev mode**: every request behaves as an analyst
but each response carries ``X-Academic-Edge-Dev-Auth: true`` so it can never be
mistaken for a secured deployment.
"""

from __future__ import annotations

from typing import Annotated

from academic_edge_domain.enums import Role
from fastapi import Depends, Header, HTTPException, Response, status

from academic_edge_api.settings import Settings, get_settings

ROLE_RANK = {Role.READER: 1, Role.ANALYST: 2, Role.ADMIN: 3}
DEV_MODE_HEADER = "X-Academic-Edge-Dev-Auth"


def current_role(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Role:
    """Resolve the caller's role, or raise 401/403."""
    role_keys = settings.role_keys
    if not role_keys:
        response.headers[DEV_MODE_HEADER] = "true"
        return Role.ANALYST
    if api_key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-API-Key header is required")
    role = role_keys.get(api_key)
    if role is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown API key")
    return role


def require_role(minimum: Role) -> Any:
    """Dependency factory: reject callers whose role ranks below ``minimum``."""

    def _guard(role: Annotated[Role, Depends(current_role)]) -> Role:
        if ROLE_RANK[role] < ROLE_RANK[minimum]:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"role {role.value} is not allowed here (needs {minimum.value})",
            )
        return role

    return _guard


from typing import Any  # noqa: E402  (kept after the guard for readability)
