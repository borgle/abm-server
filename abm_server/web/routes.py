import hashlib
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from ..api_keys import list_user_api_keys
from ..auth.dependencies import SESSION_COOKIE, AuthContext, get_current_auth, require_csrf
from ..database import get_session
from ..errors import ApiError
from ..mcp.oauth import OAUTH_SCOPE_DESCRIPTIONS
from ..models import UserRole

router = APIRouter(tags=["web"])


def _social_providers(settings) -> list[dict[str, object]]:
    if not settings.social_login_enabled:
        return []
    try:
        from abm_cloud.social import public_provider_descriptors
    except ImportError:
        return []
    return public_provider_descriptors(settings)


_PACKAGE_DIR = Path(__file__).parent
_STATIC_DIR = _PACKAGE_DIR / "static"
templates = Jinja2Templates(directory=_PACKAGE_DIR / "templates")


def _static_version() -> str:
    digest = hashlib.sha256()
    for path in sorted(_STATIC_DIR.iterdir()):
        if path.is_file():
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


templates.env.globals["asset_version"] = _static_version()


def _safe_next(value: str | None, fallback: str = "/console/overview") -> str:
    if not value:
        return fallback
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return fallback
    return value


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    settings = request.app.state.settings
    return templates.TemplateResponse(
        request,
        "landing.html",
        {
            "title": "ABM · a browser mcp",
            "signed_in": bool(request.cookies.get(SESSION_COOKIE)),
            "extension_github_url": settings.extension_github_url,
            "extension_release_url": settings.extension_release_url,
            "extension_store_url": settings.extension_store_url,
            "issuer_url": request.app.state.oauth_service.issuer_url,
            "edition": request.app.state.edition,
        },
    )


@router.get("/docs/mcp", response_class=HTMLResponse)
async def mcp_guide_page(request: Request):
    settings = request.app.state.settings
    return templates.TemplateResponse(
        request,
        "mcp-guide.html",
        {
            "title": "ABM Server MCP Guide",
            "issuer_url": request.app.state.oauth_service.issuer_url,
            "extension_release_url": settings.extension_release_url,
        },
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if not request.app.state.edition.self_registration:
        raise HTTPException(status_code=404)
    providers = _social_providers(request.app.state.settings)
    return templates.TemplateResponse(
        request,
        "register.html",
        {
            "title": "申请使用 ABM",
            "next": _safe_next(request.query_params.get("next")),
            "social_providers": providers,
            "social_needs_email": any(provider["requiresEmail"] for provider in providers),
            "edition": request.app.state.edition,
        },
    )


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        {"title": "找回密码"},
    )


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    return templates.TemplateResponse(
        request,
        "reset_password.html",
        {"title": "重置密码"},
    )


@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email_page(request: Request):
    return templates.TemplateResponse(
        request,
        "verify_email.html",
        {"title": "验证邮箱"},
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    providers = _social_providers(request.app.state.settings)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "title": "登录 ABM",
            "next": _safe_next(request.query_params.get("next")),
            "social_providers": providers,
            "social_needs_email": any(provider["requiresEmail"] for provider in providers),
            "edition": request.app.state.edition,
        },
    )


@router.get("/social/complete", response_class=HTMLResponse)
async def social_complete_page(request: Request):
    if not request.app.state.edition.self_registration:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "social_complete.html",
        {"title": "完成注册"},
    )


@router.get("/console", response_class=HTMLResponse)
async def console_page(request: Request):
    query = request.url.query
    target = "/console/overview" + (f"?{query}" if query else "")
    return RedirectResponse(target, status_code=303)


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    query = request.url.query
    target = "/admin/overview" + (f"?{query}" if query else "")
    return RedirectResponse(target, status_code=303)


_CONSOLE_WORKSPACE_SECTIONS = {
    "overview": "概览",
    "connections": "连接与 Key",
    "usage": "用量与额度",
    "account": "账号与安全",
    "help": "帮助与文档",
}

_ADMIN_WORKSPACE_SECTIONS = {
    "overview": "系统概览",
    "users": "用户",
    "approvals": "审批",
    "plans": "套餐与模型",
    "audit": "审计",
    "system": "系统设置",
    "config": "参数配置",
}

_CREATION_SECTIONS = {
    "overview": "工作台",
    "radar": "选题雷达",
    "library": "素材库",
    "studio": "创作工坊",
    "templates": "模板库",
    "assets": "资产库",
    "trash": "回收站",
    "publish": "发布计划",
}


def _workspace_response(request: Request, app: str, section: str, auth: AuthContext):
    sections = _ADMIN_WORKSPACE_SECTIONS if app == "admin" else _CONSOLE_WORKSPACE_SECTIONS
    template = (
        "admin_config.html" if app == "admin" and section == "config" else f"{app}_workspace.html"
    )
    return templates.TemplateResponse(
        request,
        template,
        {
            "app": app,
            "section": section,
            "title": sections[section],
            "page_key": f"workspace.page.{section}",
            "is_admin": auth.user.role == UserRole.ADMIN,
            "display_name": auth.user.display_name,
            "edition": request.app.state.edition,
        },
    )


@router.get("/console/{section}", response_class=HTMLResponse)
async def console_workspace_page(
    request: Request,
    section: str,
    db: AsyncSession = Depends(get_session),
):
    if section not in _CONSOLE_WORKSPACE_SECTIONS:
        raise HTTPException(status_code=404)
    try:
        auth = await get_current_auth(request, db)
    except ApiError:
        next_path = quote(request.url.path, safe="")
        return RedirectResponse(f"/login?next={next_path}", status_code=303)
    return _workspace_response(request, "console", section, auth)


@router.get("/admin/{section}", response_class=HTMLResponse)
async def admin_workspace_page(
    request: Request,
    section: str,
    db: AsyncSession = Depends(get_session),
):
    if section not in _ADMIN_WORKSPACE_SECTIONS:
        raise HTTPException(status_code=404)
    edition = request.app.state.edition
    if section == "users" and not edition.admin_users:
        raise HTTPException(status_code=404)
    if section == "approvals" and not edition.approvals:
        raise HTTPException(status_code=404)
    if section == "audit" and not edition.audit:
        raise HTTPException(status_code=404)
    try:
        auth = await get_current_auth(request, db)
    except ApiError:
        next_path = quote(request.url.path, safe="")
        return RedirectResponse(f"/login?next={next_path}", status_code=303)
    if auth.user.role != UserRole.ADMIN:
        return RedirectResponse("/console/overview", status_code=303)
    return _workspace_response(request, "admin", section, auth)


@router.get("/creation", response_class=HTMLResponse)
async def creation_root(request: Request):
    return RedirectResponse("/creation/overview", status_code=303)


@router.get("/creation/{section}", response_class=HTMLResponse)
async def creation_page(
    request: Request,
    section: str,
    db: AsyncSession = Depends(get_session),
):
    if section not in _CREATION_SECTIONS:
        raise HTTPException(status_code=404)
    try:
        auth = await get_current_auth(request, db)
    except ApiError:
        next_path = quote(request.url.path, safe="")
        return RedirectResponse(f"/login?next={next_path}", status_code=303)
    template = f"creation_{section}.html"
    return templates.TemplateResponse(
        request,
        template,
        {
            "app": "creation",
            "section": section,
            "title": _CREATION_SECTIONS[section],
            "page_key": f"workspace.page.{section}",
            "is_admin": auth.user.role == UserRole.ADMIN,
            "display_name": auth.user.display_name,
            "edition": request.app.state.edition,
        },
    )


@router.get("/video-bridge", response_class=HTMLResponse)
async def video_bridge_page(request: Request):
    return templates.TemplateResponse(
        request,
        "video-bridge.html",
        {"title": "视频桥"},
    )


@router.get("/oauth/authorize", response_class=HTMLResponse)
async def oauth_authorize_page(
    request: Request,
    request_id: str = "",
    db: AsyncSession = Depends(get_session),
):
    oauth = request.app.state.oauth_service
    pending = await oauth.get_pending_authorization(request_id, session=db) if request_id else None
    if pending is None:
        return templates.TemplateResponse(
            request,
            "oauth_consent.html",
            {
                "title": "MCP 授权",
                "error": "授权请求不存在或已过期。请回到 MCP 客户端重新发起连接。",
            },
            status_code=400,
        )

    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        next_path = "/oauth/authorize?" + urlencode({"request_id": request_id})
        return RedirectResponse(f"/login?next={quote(next_path, safe='')}", status_code=303)
    try:
        auth = await get_current_auth(request, db)
    except ApiError:
        next_path = "/oauth/authorize?" + urlencode({"request_id": request_id})
        return RedirectResponse(f"/login?next={quote(next_path, safe='')}", status_code=303)

    scopes = [
        {
            "name": scope,
            "description": OAUTH_SCOPE_DESCRIPTIONS.get(scope, scope),
        }
        for scope in pending.scopes
    ]
    gateway = request.app.state.extension_gateway
    connections = []
    for key in await list_user_api_keys(db, auth.user.id):
        if key.revoked_at is not None:
            continue
        info = gateway.connection_info(key.id)
        connections.append(
            {
                "id": key.id,
                "name": key.name,
                "prefix": key.public_prefix,
                "online": info is not None,
            }
        )
    return templates.TemplateResponse(
        request,
        "oauth_consent.html",
        {
            "title": "MCP 授权",
            "request_id": request_id,
            "client_name": pending.client_name,
            "scopes": scopes,
            "account_email": auth.user.email,
            "account_name": auth.user.display_name,
            "connections": connections,
            "error": None,
        },
    )


@router.post("/oauth/authorize")
async def oauth_authorize_decision(
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "ABM_VALIDATION_ERROR",
                    "message": "Request body must be JSON.",
                }
            },
        )
    request_id = body.get("requestId")
    decision = body.get("decision")
    if not isinstance(request_id, str) or not request_id:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "ABM_VALIDATION_ERROR",
                    "message": "requestId must not be empty.",
                }
            },
        )
    if decision not in {"approve", "deny"}:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "ABM_VALIDATION_ERROR",
                    "message": "decision must be approve or deny.",
                }
            },
        )
    connection_mode = body.get("connectionMode") or "auto"
    connection_ids = body.get("connectionIds") or []
    if not isinstance(connection_mode, str):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "ABM_VALIDATION_ERROR",
                    "message": "connectionMode must be a string.",
                }
            },
        )
    if not isinstance(connection_ids, list) or not all(
        isinstance(item, str) for item in connection_ids
    ):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "ABM_VALIDATION_ERROR",
                    "message": "connectionIds must be an array of strings.",
                }
            },
        )
    oauth = request.app.state.oauth_service
    if decision == "approve":
        redirect = await oauth.approve_authorization(
            request_id,
            user=auth.user,
            connection_mode=connection_mode,
            connection_ids=connection_ids,
            session=db,
        )
    else:
        redirect = await oauth.deny_authorization(request_id, session=db)
    return JSONResponse({"redirect": redirect})
