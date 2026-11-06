from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...accounts import REGISTRATION_APPROVAL_SETTING, get_setting
from ...admin import update_registration_approval
from ...admin.creation_config import (
    create_provider,
    delete_provider,
    load_config,
    public_config,
    save_config,
    test_provider,
    update_provider,
    update_system,
)
from ...admin.system_config import (
    config_payload,
    export_payload,
    load_overrides,
    save_overrides,
)
from ...auth.dependencies import AuthContext, require_admin, require_admin_csrf
from ...database import get_session
from ...errors import ApiError
from ...schemas import (
    AdminSystemPatch,
    CreationProviderCreate,
    CreationProviderPatch,
    LocalModelPatch,
    SystemConfigImport,
    SystemConfigPatch,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/local-model")
async def get_local_model(
    request: Request,
    _auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    config = await load_config(db)
    return {
        "ok": True,
        "local": config["local"],
        "providers": public_config(config)["providers"],
    }


_LOCAL_FIELD_MAP = {
    "provider_id": "providerId",
    "model": "model",
    "fallback_model": "fallbackModel",
    "image_provider_id": "imageProviderId",
    "image_model": "imageModel",
    "image_max_n": "imageMaxN",
}


@router.put("/local-model")
async def put_local_model(
    payload: LocalModelPatch,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    config = await load_config(db)
    known = {provider["id"] for provider in config["providers"] if provider.get("id")}
    values = {
        _LOCAL_FIELD_MAP[key]: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if key in _LOCAL_FIELD_MAP and value is not None
    }
    for field in ("providerId", "imageProviderId"):
        if values.get(field) and values[field] not in known:
            raise ApiError(400, "ABM_VALIDATION_ERROR", "Unknown provider.")
    config["local"].update(values)
    await save_config(db, config, auth.user)
    await db.commit()
    return {"ok": True, "local": config["local"]}


@router.get("/creation/providers")
async def list_creation_providers(
    request: Request,
    _auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    config = await load_config(db)
    return {"ok": True, "providers": public_config(config)["providers"]}


@router.post("/creation/providers", status_code=201)
async def create_creation_provider(
    payload: CreationProviderCreate,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    provider = await create_provider(
        db,
        request.app.state.settings,
        auth.user,
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
    )
    await db.commit()
    return {"ok": True, "provider": provider}


@router.patch("/creation/providers/{provider_id}")
async def patch_creation_provider(
    provider_id: str,
    payload: CreationProviderPatch,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    provider = await update_provider(
        db,
        request.app.state.settings,
        auth.user,
        provider_id,
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
    )
    await db.commit()
    return {"ok": True, "provider": provider}


@router.delete("/creation/providers/{provider_id}", status_code=204)
async def remove_creation_provider(
    provider_id: str,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> None:
    await delete_provider(db, auth.user, provider_id)
    await db.commit()


@router.post("/creation/providers/{provider_id}/test")
async def test_creation_provider(
    provider_id: str,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    result = await test_provider(
        db,
        request.app.state.settings,
        auth.user,
        provider_id,
    )
    await db.commit()
    return {"ok": result["ok"], "provider": result, "message": result["message"]}


@router.get("/system/config")
async def get_system_config(
    request: Request,
    auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    overrides = await load_overrides(db)
    return config_payload(request.app.state.settings, overrides)


@router.patch("/system/config")
async def patch_system_config(
    payload: SystemConfigPatch,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    result = await save_overrides(db, request.app.state.settings, auth.user, payload.values)
    await db.commit()
    return result


@router.get("/system/config/export")
async def export_system_config(
    request: Request,
    auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    overrides = await load_overrides(db)
    payload = export_payload(request.app.state.settings, overrides)
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": 'attachment; filename="abm-system-config.json"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/system/config/import")
async def import_system_config(
    payload: SystemConfigImport,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    result = await save_overrides(
        db,
        request.app.state.settings,
        auth.user,
        payload.values,
        replace=payload.mode == "replace",
        base=getattr(request.app.state, "config_base", None),
    )
    await db.commit()
    return result


@router.get("/system")
async def get_admin_system(
    request: Request,
    _auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    registration = bool(
        await get_setting(
            db,
            REGISTRATION_APPROVAL_SETTING,
            request.app.state.settings.registration_require_approval,
        )
    )
    config = public_config(await load_config(db))
    return {"ok": True, "registrationRequireApproval": registration, **config}


@router.patch("/system")
async def patch_admin_system(
    payload: AdminSystemPatch,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    if payload.registration_require_approval is not None:
        await update_registration_approval(
            db,
            value=payload.registration_require_approval,
            actor=auth.user,
        )
    values = {
        "enabled": payload.enabled,
        "byokEnabled": payload.byok_enabled,
        "retentionDays": payload.retention_days,
        "trashDays": payload.trash_days,
    }
    await update_system(db, auth.user, values)
    await db.commit()
    registration = bool(
        await get_setting(
            db,
            REGISTRATION_APPROVAL_SETTING,
            request.app.state.settings.registration_require_approval,
        )
    )
    config = public_config(await load_config(db))
    return {"ok": True, "registrationRequireApproval": registration, **config}


__all__ = [
    "router",
    "get_local_model",
    "put_local_model",
    "list_creation_providers",
    "create_creation_provider",
    "patch_creation_provider",
    "remove_creation_provider",
    "test_creation_provider",
    "get_system_config",
    "patch_system_config",
    "export_system_config",
    "import_system_config",
    "get_admin_system",
    "patch_admin_system",
]
