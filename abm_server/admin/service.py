"""Thin core wrapper for the registration approval toggle.

The implementation lives in ``abm_cloud.provisioning``. Without the
private cloud package the call fails, which keeps the open-source build
single-user only.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models import User


async def update_registration_approval(
    session: AsyncSession,
    *,
    value: bool,
    actor: User,
) -> None:
    try:
        from abm_cloud.provisioning import update_registration_approval as update
    except ImportError as exc:
        raise ApiError(
            404,
            "ABM_NOT_FOUND",
            "Registration approval is not available on this server.",
        ) from exc
    await update(session, value=value, actor=actor)
