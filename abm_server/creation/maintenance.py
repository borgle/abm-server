"""Retention and recycle-bin maintenance for creation data."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select

from ..database import Database
from ..models import CreationAsset, CreationAssetVersion, CreationSource, utcnow


async def cleanup_creation_data(
    database: Database,
    *,
    retention_days: int = 30,
    trash_days: int = 10,
    now: datetime | None = None,
) -> dict[str, int]:
    """Run both retention stages.

    Stage one moves sources past their retention window into the recycle bin.
    Stage two hard-deletes recycle-bin rows whose grace period is over. The
    function is idempotent and safe to run repeatedly.
    """
    moment = now or utcnow()
    retention_cutoff = moment - timedelta(days=max(1, retention_days))
    trashed = 0
    purged_sources = 0
    purged_assets = 0

    async with database.sessions() as session:
        expired = (
            await session.scalars(
                select(CreationSource).where(
                    CreationSource.trashed_at.is_(None),
                    CreationSource.fetched_at <= retention_cutoff,
                )
            )
        ).all()
        for source in expired:
            source.trashed_at = moment
            source.purge_after = moment + timedelta(days=max(1, trash_days))
            source.trash_reason = "expired"
            trashed += 1

        due_sources = (
            await session.scalars(
                select(CreationSource).where(
                    CreationSource.trashed_at.is_not(None),
                    CreationSource.purge_after.is_not(None),
                    CreationSource.purge_after <= moment,
                )
            )
        ).all()
        for source in due_sources:
            await session.delete(source)
            purged_sources += 1

        due_assets = (
            await session.scalars(
                select(CreationAsset).where(
                    CreationAsset.trashed_at.is_not(None),
                    CreationAsset.purge_after.is_not(None),
                    CreationAsset.purge_after <= moment,
                )
            )
        ).all()
        for asset in due_assets:
            await session.execute(
                delete(CreationAssetVersion).where(CreationAssetVersion.asset_id == asset.id)
            )
            await session.delete(asset)
            purged_assets += 1

        await session.commit()

    return {
        "trashedSources": trashed,
        "purgedSources": purged_sources,
        "purgedAssets": purged_assets,
    }


__all__ = ["cleanup_creation_data"]
