from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models import CreationAsset, CreationAssetVersion, CreationProject, User, utcnow


def _project_dict(project: CreationProject, asset_count: int = 0) -> dict:
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "defaultPlatform": project.default_platform,
        "assetCount": asset_count,
        "createdAt": project.created_at.isoformat(),
        "updatedAt": project.updated_at.isoformat(),
    }


def _version_dict(version: CreationAssetVersion) -> dict:
    return {
        "id": version.id,
        "assetId": version.asset_id,
        "versionNo": version.version_no,
        "parentVersionId": version.parent_version_id,
        "contentMd": version.content_md,
        "outline": version.outline,
        "brief": version.brief,
        "citations": version.citations,
        "sourceIds": version.source_ids,
        "modelSource": version.model_source,
        "model": version.model,
        "tokensIn": version.tokens_in,
        "tokensOut": version.tokens_out,
        "createdBy": version.created_by,
        "createdAt": version.created_at.isoformat(),
    }


def _asset_dict(asset: CreationAsset) -> dict:
    return {
        "id": asset.id,
        "projectId": asset.project_id,
        "title": asset.title,
        "kind": asset.kind,
        "status": asset.status,
        "currentVersionId": asset.current_version_id,
        "masterPlatform": asset.master_platform,
        "tags": asset.tags or [],
        "createdAt": asset.created_at.isoformat(),
        "updatedAt": asset.updated_at.isoformat(),
    }


async def list_projects(session: AsyncSession, user_id: str) -> list[CreationProject]:
    query = (
        select(CreationProject)
        .where(
            CreationProject.user_id == user_id,
            CreationProject.archived_at.is_(None),
        )
        .order_by(CreationProject.updated_at.desc())
    )
    return list((await session.scalars(query)).all())


async def project_asset_counts(session: AsyncSession, user_id: str) -> dict[str, int]:
    rows = await session.execute(
        select(CreationAsset.project_id, func.count(CreationAsset.id))
        .where(
            CreationAsset.user_id == user_id,
            CreationAsset.trashed_at.is_(None),
            CreationAsset.archived_at.is_(None),
            CreationAsset.project_id.is_not(None),
        )
        .group_by(CreationAsset.project_id)
    )
    return {str(project_id): int(count) for project_id, count in rows.all()}


async def create_project(
    session: AsyncSession,
    user: User,
    *,
    title: str,
    description: str | None = None,
    default_platform: str = "master",
) -> CreationProject:
    clean = title.strip()
    if not clean:
        raise ApiError(422, "ABM_VALIDATION_ERROR", "Project title must not be empty.")
    project = CreationProject(
        user_id=user.id,
        title=clean[:160],
        description=(description or "").strip() or None,
        default_platform=default_platform[:32] or "master",
    )
    session.add(project)
    await session.flush()
    return project


async def get_project(session: AsyncSession, user_id: str, project_id: str) -> CreationProject:
    project = await session.get(CreationProject, project_id)
    if project is None or project.user_id != user_id or project.archived_at is not None:
        raise ApiError(404, "ABM_NOT_FOUND", "Project not found.")
    return project


async def update_project(
    session: AsyncSession,
    user_id: str,
    project_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    default_platform: str | None = None,
) -> CreationProject:
    project = await get_project(session, user_id, project_id)
    if title is not None:
        clean = title.strip()
        if not clean:
            raise ApiError(422, "ABM_VALIDATION_ERROR", "Project title must not be empty.")
        project.title = clean[:160]
    if description is not None:
        project.description = description.strip() or None
    if default_platform is not None:
        project.default_platform = default_platform[:32] or "master"
    project.updated_at = utcnow()
    return project


async def archive_project(
    session: AsyncSession,
    user_id: str,
    project_id: str,
) -> None:
    project = await get_project(session, user_id, project_id)
    project.archived_at = utcnow()
    await session.execute(
        update(CreationAsset)
        .where(
            CreationAsset.user_id == user_id,
            CreationAsset.project_id == project_id,
        )
        .values(project_id=None)
    )


async def list_assets(
    session: AsyncSession,
    user_id: str,
    *,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CreationAsset]:
    query = select(CreationAsset).where(
        CreationAsset.user_id == user_id,
        CreationAsset.trashed_at.is_(None),
        CreationAsset.archived_at.is_(None),
    )
    if project_id:
        query = query.where(CreationAsset.project_id == project_id)
    if status:
        query = query.where(CreationAsset.status == status)
    query = query.order_by(CreationAsset.updated_at.desc()).limit(limit).offset(offset)
    return list((await session.scalars(query)).all())


async def count_assets(
    session: AsyncSession,
    user_id: str,
    *,
    project_id: str | None = None,
    status: str | None = None,
) -> int:
    query = select(func.count(CreationAsset.id)).where(
        CreationAsset.user_id == user_id,
        CreationAsset.trashed_at.is_(None),
        CreationAsset.archived_at.is_(None),
    )
    if project_id:
        query = query.where(CreationAsset.project_id == project_id)
    if status:
        query = query.where(CreationAsset.status == status)
    return int(await session.scalar(query) or 0)


async def get_asset(session: AsyncSession, user_id: str, asset_id: str) -> CreationAsset:
    asset = await session.get(CreationAsset, asset_id)
    if (
        asset is None
        or asset.user_id != user_id
        or asset.trashed_at is not None
        or asset.archived_at is not None
    ):
        raise ApiError(404, "ABM_NOT_FOUND", "Asset not found.")
    return asset


async def create_asset(
    session: AsyncSession,
    user: User,
    *,
    title: str,
    kind: str = "article",
    project_id: str | None = None,
    platform: str = "master",
    content_md: str = "",
    outline: list | None = None,
    brief: dict | None = None,
    citations: list | None = None,
    source_ids: list | None = None,
    created_by: str = "user",
    model_source: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> CreationAsset:
    clean = title.strip()
    if not clean:
        raise ApiError(422, "ABM_VALIDATION_ERROR", "Asset title must not be empty.")
    if project_id:
        await get_project(session, user.id, project_id)
    asset = CreationAsset(
        user_id=user.id,
        project_id=project_id,
        title=clean[:200],
        kind=kind[:32] or "article",
        master_platform=platform[:32] or "master",
        tags=[],
    )
    session.add(asset)
    await session.flush()
    version = CreationAssetVersion(
        asset_id=asset.id,
        user_id=user.id,
        version_no=1,
        content_md=content_md,
        outline=outline or [],
        brief=brief or {},
        citations=citations or [],
        source_ids=source_ids or [],
        created_by=created_by[:16],
        model_source=model_source,
        model=model,
        prompt_version=prompt_version,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    asset.updated_at = utcnow()
    return asset


async def update_asset(
    session: AsyncSession,
    user_id: str,
    asset_id: str,
    *,
    title: str | None = None,
    status: str | None = None,
    platform: str | None = None,
    tags: list | None = None,
) -> CreationAsset:
    asset = await get_asset(session, user_id, asset_id)
    if title is not None:
        clean = title.strip()
        if not clean:
            raise ApiError(422, "ABM_VALIDATION_ERROR", "Asset title must not be empty.")
        asset.title = clean[:200]
    if status is not None:
        if status not in {"draft", "review", "approved", "published", "archived"}:
            raise ApiError(422, "ABM_VALIDATION_ERROR", "Unknown asset status.")
        asset.status = status
    if platform is not None:
        asset.master_platform = platform[:32] or "master"
    if tags is not None:
        asset.tags = tags
    asset.updated_at = utcnow()
    return asset


async def trash_asset(session: AsyncSession, user_id: str, asset_id: str) -> None:
    asset = await get_asset(session, user_id, asset_id)
    now = utcnow()
    asset.trashed_at = now
    asset.purge_after = now + timedelta(days=10)
    asset.trash_reason = "manual"


async def restore_asset(
    session: AsyncSession,
    user_id: str,
    asset_id: str,
    *,
    trash_days: int = 10,
) -> CreationAsset:
    asset = await session.get(CreationAsset, asset_id)
    if asset is None or asset.user_id != user_id or asset.trashed_at is None:
        raise ApiError(404, "ABM_NOT_FOUND", "Asset not found in the recycle bin.")
    asset.trashed_at = None
    asset.purge_after = None
    asset.trash_reason = None
    asset.updated_at = utcnow()
    return asset


async def purge_asset(session: AsyncSession, user_id: str, asset_id: str) -> None:
    asset = await session.get(CreationAsset, asset_id)
    if asset is None or asset.user_id != user_id or asset.trashed_at is None:
        raise ApiError(404, "ABM_NOT_FOUND", "Asset not found in the recycle bin.")
    await session.execute(
        delete(CreationAssetVersion).where(CreationAssetVersion.asset_id == asset.id)
    )
    await session.delete(asset)


async def list_versions(
    session: AsyncSession,
    user_id: str,
    asset_id: str,
) -> list[CreationAssetVersion]:
    await get_asset(session, user_id, asset_id)
    query = (
        select(CreationAssetVersion)
        .where(
            CreationAssetVersion.asset_id == asset_id,
            CreationAssetVersion.user_id == user_id,
        )
        .order_by(CreationAssetVersion.version_no.desc())
    )
    return list((await session.scalars(query)).all())


async def create_version(
    session: AsyncSession,
    user_id: str,
    asset_id: str,
    *,
    content_md: str,
    title: str | None = None,
    outline: list | None = None,
    brief: dict | None = None,
    citations: list | None = None,
    source_ids: list | None = None,
    created_by: str = "user",
    model_source: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> CreationAssetVersion:
    asset = await get_asset(session, user_id, asset_id)
    latest = await session.scalar(
        select(func.max(CreationAssetVersion.version_no)).where(
            CreationAssetVersion.asset_id == asset_id
        )
    )
    version = CreationAssetVersion(
        asset_id=asset_id,
        user_id=user_id,
        version_no=int(latest or 0) + 1,
        parent_version_id=asset.current_version_id,
        content_md=content_md,
        outline=outline or [],
        brief=brief or {},
        citations=citations or [],
        source_ids=source_ids or [],
        created_by=created_by[:16],
        model_source=model_source,
        model=model,
        prompt_version=prompt_version,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    if title is not None:
        clean = title.strip()
        if not clean:
            raise ApiError(422, "ABM_VALIDATION_ERROR", "Asset title must not be empty.")
        asset.title = clean[:200]
    asset.updated_at = utcnow()
    return version


PLATFORMS = [
    {
        "id": "master",
        "name": "主稿",
        "kind": "article",
        "titleLimit": None,
        "bodyLimit": None,
        "tagsLimit": None,
    },
    {
        "id": "xiaohongshu",
        "name": "小红书",
        "kind": "note",
        "titleLimit": 20,
        "bodyLimit": 1000,
        "tagsLimit": [5, 10],
    },
    {
        "id": "wechat",
        "name": "公众号",
        "kind": "article",
        "titleLimit": 64,
        "bodyLimit": 5000,
        "tagsLimit": None,
    },
    {
        "id": "shipinhao",
        "name": "视频号",
        "kind": "script",
        "titleLimit": 30,
        "bodyLimit": 2000,
        "tagsLimit": 10,
    },
    {
        "id": "zhihu",
        "name": "知乎",
        "kind": "answer",
        "titleLimit": 100,
        "bodyLimit": 10000,
        "tagsLimit": None,
    },
]


def public_asset(asset: CreationAsset) -> dict:
    return _asset_dict(asset)


def public_version(version: CreationAssetVersion) -> dict:
    return _version_dict(version)


def public_project(project: CreationProject, asset_count: int = 0) -> dict:
    return _project_dict(project, asset_count)
