"""API auth dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


async def require_admin_api_key(
    x_admin_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Protect mutation/admin endpoints with a shared API key.

    Development and tests remain usable without a configured key. In any
    deployed environment, setting ADMIN_API_KEY makes the header mandatory.
    """
    expected = get_settings().admin_api_key
    if not expected:
        return
    if x_admin_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid admin API key",
        )
