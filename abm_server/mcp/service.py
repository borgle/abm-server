from __future__ import annotations

import contextvars
import json
import logging
import secrets
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
from mcp import types
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import (
    StreamableHTTPASGIApp,
    StreamableHTTPSessionManager,
)
from pydantic import ValidationError
from starlette.types import ASGIApp, Receive, Scope, Send

from .. import __version__
from ..accounts import (
    REGISTRATION_APPROVAL_SETTING,
    get_setting,
    register_user,
    revoke_user_sessions,
)
from ..api_keys import (
    active_key_count,
    create_api_key,
    key_limit_for_user,
    list_user_api_keys,
    revoke_api_key,
)
from ..audit import record_audit
from ..auth.dependencies import RuntimeAuth
from ..auth.scopes import ACCOUNT_READ, ACCOUNT_WRITE, BROWSER
from ..auth.security import hash_password, verify_password
from ..concurrency import KeyedLockPool, SlidingWindowLimiter
from ..config import Settings
from ..database import Database
from ..email import EmailService
from ..errors import ApiError, error_body
from ..extension_gateway import ExtensionGateway, GatewayCallError, SessionError
from ..models import (
    ApiKey,
    User,
    UserRole,
    UserStatus,
    utcnow,
)
from ..notices import NotificationService
from ..schemas import (
    ApiKeyCreateResponse,
    ApiKeyResponse,
    RegisterRequest,
    UserResponse,
)
from ..tiers import tier_for
from ..usage import UsageService
from ..video import VideoError, VideoService
from .oauth import OAuthService
from .tools import (
    ADMIN_TOOL_BY_NAME,
    ADMIN_TOOLS,
    AUTHENTICATED_TOOLS,
    PUBLIC_TOOL_BY_NAME,
    PUBLIC_TOOLS,
    TOOL_BY_NAME,
)

logger = logging.getLogger(__name__)

runtime_auth_var: contextvars.ContextVar[RuntimeAuth | None] = contextvars.ContextVar(
    "abm_mcp_runtime_auth",
    default=None,
)
request_context_var: contextvars.ContextVar[dict[str, str | None] | None] = contextvars.ContextVar(
    "abm_mcp_request_context",
    default=None,
)


def _json_result(payload: Any, *, is_error: bool = False) -> types.CallToolResult:
    structured = payload if isinstance(payload, dict) else {"result": payload}
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structuredContent=structured,
        isError=is_error,
    )


def _error_result(
    *,
    code: str,
    message: str,
    retryable: bool = False,
    action: str = "none",
) -> types.CallToolResult:
    payload = {
        "code": code,
        "message": message,
        "retryable": retryable,
        "action": action,
    }
    text = json.dumps({"error": payload}, ensure_ascii=False)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structuredContent={"error": payload},
        isError=True,
    )


def _api_error_result(exc: ApiError) -> types.CallToolResult:
    return _error_result(
        code=exc.code,
        message=exc.message,
        retryable=exc.retryable,
        action=exc.action,
    )


def _gateway_error_result(exc: GatewayCallError) -> types.CallToolResult:
    return _error_result(
        code=exc.code,
        message=exc.message,
        retryable=exc.retryable,
        action=exc.action,
    )


def _validation_error_result(exc: ValidationError | ValueError) -> types.CallToolResult:
    if isinstance(exc, ValidationError):
        details = [
            {
                "location": list(error.get("loc", ())),
                "message": error.get("msg", "invalid value"),
            }
            for error in exc.errors()
        ]
        message = "Parameter validation failed."
    else:
        details = [{"message": str(exc)}]
        message = str(exc) or "Parameter validation failed."
    return _json_result(
        {
            "error": {
                "code": "ABM_VALIDATION_ERROR",
                "message": message,
                "retryable": False,
                "action": "none",
                "details": details,
            }
        },
        is_error=True,
    )


def _normalize_extension_result(payload: dict[str, Any]) -> types.CallToolResult:
    content: list[types.TextContent] = []
    for item in payload.get("content", []):
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                content.append(types.TextContent(type="text", text=text))
                continue
        content.append(types.TextContent(type="text", text=json.dumps(item, ensure_ascii=False)))
    if not content:
        content.append(types.TextContent(type="text", text="{}"))
    return types.CallToolResult(content=content, isError=False)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _user_payload(user: User, settings: Settings) -> dict[str, Any]:
    payload = UserResponse.model_validate(user).model_dump(by_alias=True, mode="json")
    payload["planCode"] = tier_for(user, settings)
    payload["apiKeyLimit"] = key_limit_for_user(user, settings)
    return payload


def _api_key_payload(key: ApiKey, *, plaintext: str | None = None) -> dict[str, Any]:
    response = ApiKeyCreateResponse if plaintext is not None else ApiKeyResponse
    data = response(
        id=key.id,
        name=key.name,
        prefix=key.public_prefix,
        status="revoked" if key.revoked_at else "active",
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
        **({"plaintext": plaintext} if plaintext is not None else {}),
    )
    return data.model_dump(by_alias=True, mode="json")


def _client_ip(scope: Scope) -> str | None:
    # Uvicorn's proxy-header middleware already resolves trusted forwarded
    # addresses into ``scope["client"]``. Reading X-Forwarded-For directly
    # would let untrusted clients spoof their address and bypass rate limits.
    client = scope.get("client")
    if client:
        return str(client[0])[:64]
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return None


def _unauthorized_response(
    *,
    oauth: OAuthService,
    code: str,
    message: str,
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    request_id = f"req_{uuid4().hex}"
    body = error_body(
        code=code,
        message=message,
        request_id=request_id,
        retryable=False,
        action="open_account_portal",
    )
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    challenge = (
        f'Bearer resource_metadata="{oauth.resource_metadata_url}", '
        f'error="invalid_token", error_description="{code}"'
    )
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(payload)).encode("ascii")),
        (b"x-request-id", request_id.encode("ascii")),
        (b"www-authenticate", challenge.encode("utf-8")),
    ]
    return 401, headers, payload


class McpAuthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        database: Database,
        oauth: OAuthService,
        gateway: ExtensionGateway,
    ):
        self.app = app
        self.database = database
        self.oauth = oauth
        self.gateway = gateway

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        method = str(scope.get("method", "")).upper()
        mcp_session_id = headers.get("mcp-session-id")
        authorization = headers.get("authorization", "")
        token = ""
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()

        auth: RuntimeAuth | None = None
        access_token: AccessToken | None = None
        invalid_code = "ABM_INVALID_TOKEN"
        invalid_message = "Missing or invalid OAuth access token."
        try:
            if token:
                access = await self.oauth.provider.load_access_token(token)
                if access is None or not access.subject:
                    invalid_message = "OAuth access token is invalid or expired."
                else:
                    async with self.database.sessions() as db:
                        user = await db.get(User, access.subject)
                    if user is None or user.status != UserStatus.ACTIVE:
                        invalid_message = "The account for this OAuth access token is unavailable."
                    else:
                        claims = access.claims or {}
                        auth = RuntimeAuth(
                            user=user,
                            api_key=None,
                            auth_kind="oauth",
                            scopes=tuple(access.scopes),
                            access_token_id=claims.get("token_id"),
                            connection_mode=str(claims.get("connection_mode") or "auto"),
                            connection_ids=tuple(claims.get("connection_ids") or ()),
                        )
                        scope_fingerprint = ",".join(sorted(access.scopes))
                        access_token = access.model_copy(
                            update={
                                "client_id": (
                                    f"{access.client_id}|role:{user.role}"
                                    f"|scopes:{scope_fingerprint}"
                                )
                            }
                        )
        except ApiError as exc:
            status, res_headers, payload = _unauthorized_response(
                oauth=self.oauth,
                code=exc.code,
                message=exc.message,
            )
            await send({"type": "http.response.start", "status": status, "headers": res_headers})
            await send({"type": "http.response.body", "body": payload})
            return

        if auth is None or access_token is None:
            status, res_headers, payload = _unauthorized_response(
                oauth=self.oauth,
                code=invalid_code,
                message=invalid_message,
            )
            await send({"type": "http.response.start", "status": status, "headers": res_headers})
            await send({"type": "http.response.body", "body": payload})
            return

        # The MCP session manager binds a session to the credential that
        # created it. Without this, a leaked session id could be reused with
        # another valid token and would keep the original token's privileges.
        scope["user"] = AuthenticatedUser(access_token)
        scope["abm_auth"] = auth
        auth_token = runtime_auth_var.set(auth)
        request_token = request_context_var.set(
            {
                "client_ip": _client_ip(scope),
                "user_agent": headers.get("user-agent", "")[:512],
                "mcp_session_id": mcp_session_id,
            }
        )
        try:
            await self.app(scope, receive, send)
        finally:
            if method == "DELETE" and mcp_session_id:
                await self.gateway.release_session(auth.user.id, mcp_session_id)
            runtime_auth_var.reset(auth_token)
            request_context_var.reset(request_token)


class McpPublicMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        client_ip = _client_ip(scope)
        scope["user"] = AuthenticatedUser(
            AccessToken(
                token="",
                client_id=f"public:{client_ip or 'unknown'}",
                scopes=[],
            )
        )
        token = request_context_var.set(
            {
                "client_ip": client_ip,
                "user_agent": headers.get("user-agent", "")[:512],
            }
        )
        try:
            await self.app(scope, receive, send)
        finally:
            request_context_var.reset(token)


class McpPathMiddleware:
    def __init__(self, app: ASGIApp, *, mcp_app: ASGIApp, public_mcp_app: ASGIApp):
        self.app = app
        self.mcp_app = mcp_app
        self.public_mcp_app = public_mcp_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope["path"].rstrip("/") or "/"
            if path == "/mcp/public":
                await self.public_mcp_app(scope, receive, send)
                return
            if path == "/mcp":
                await self.mcp_app(scope, receive, send)
                return
        await self.app(scope, receive, send)


class McpService:
    def __init__(
        self,
        database: Database,
        gateway: ExtensionGateway,
        video: VideoService,
        settings: Settings,
        *,
        usage: UsageService,
        email: EmailService,
        notifications: NotificationService,
    ):
        self.database = database
        self.gateway = gateway
        self.video = video
        self.settings = settings
        self.usage = usage
        self.email = email
        self.notifications = notifications
        self.oauth = OAuthService(database, settings)
        self.key_locks = KeyedLockPool()
        self.registration_limiter = SlidingWindowLimiter()

        self.server: Server = Server(
            name="abm-browser-mcp",
            version=__version__,
            instructions=(
                "ABM browser MCP. Browser tools drive the user's own Chrome extension; "
                "account tools manage the current account, API keys, and administrator actions."
            ),
        )
        self.public_server: Server = Server(
            name="abm-browser-mcp-public",
            version=__version__,
            instructions="ABM public MCP endpoint. Only the account_register tool is available.",
        )
        self._register_handlers(self.server, public=False)
        self._register_handlers(self.public_server, public=True)
        self.session_manager = StreamableHTTPSessionManager(
            app=self.server,
            json_response=True,
            stateless=False,
        )
        self.public_session_manager = StreamableHTTPSessionManager(
            app=self.public_server,
            json_response=True,
            stateless=False,
        )
        self.asgi = McpAuthMiddleware(
            StreamableHTTPASGIApp(self.session_manager),
            database,
            self.oauth,
            gateway,
        )
        self.public_asgi = McpPublicMiddleware(StreamableHTTPASGIApp(self.public_session_manager))

    @asynccontextmanager
    async def run(self):
        async with self.public_session_manager.run(), self.session_manager.run():
            yield

    def _register_handlers(self, server: Server, *, public: bool) -> None:
        async def list_tools(ctx: Any, params: types.PaginatedRequestParams):
            del params
            if public:
                return types.ListToolsResult(tools=list(PUBLIC_TOOLS))
            auth = self._auth_from_ctx(ctx)
            tools = list(AUTHENTICATED_TOOLS)
            if auth is not None and auth.user.role == UserRole.ADMIN:
                tools.extend(ADMIN_TOOLS)
            return types.ListToolsResult(tools=tools)

        async def call_tool(ctx: Any, params: types.CallToolRequestParams):
            if public:
                if params.name not in PUBLIC_TOOL_BY_NAME:
                    return _error_result(
                        code="ABM_TOOL_NOT_FOUND",
                        message=f"Tool {params.name} is not available on the public MCP endpoint.",
                    )
                return await self._call_public_tool(params.name, params.arguments or {})
            return await self._call_authenticated_tool(
                params.name,
                params.arguments or {},
                ctx,
            )

        server.add_request_handler("tools/list", types.PaginatedRequestParams, list_tools)
        server.add_request_handler("tools/call", types.CallToolRequestParams, call_tool)

    async def _call_public_tool(
        self,
        name: str,
        args: dict[str, Any],
    ) -> types.CallToolResult:
        if name != "account_register":
            return _error_result(
                code="ABM_TOOL_NOT_FOUND",
                message=f"Unknown public tool: {name}",
            )
        context = request_context_var.get() or {}
        key = context.get("client_ip") or "unknown"
        retry_after = await self.registration_limiter.hit(
            f"mcp-register:{key}",
            limit=10,
            window_seconds=15 * 60,
        )
        if retry_after:
            return _error_result(
                code="ABM_RATE_LIMITED",
                message=f"Too many registration requests. Retry in {retry_after} seconds.",
                retryable=True,
                action="wait",
            )
        try:
            return await self._account_register(args)
        except (ValidationError, ValueError) as exc:
            return _validation_error_result(exc)
        except ApiError as exc:
            return _api_error_result(exc)
        except Exception:
            logger.exception("MCP public tool failed: %s", name)
            return _error_result(
                code="ABM_INTERNAL_ERROR",
                message="Tool execution failed.",
                retryable=True,
                action="wait",
            )

    def _auth_from_ctx(self, ctx: Any) -> RuntimeAuth | None:
        request = getattr(ctx, "request", None)
        if request is not None:
            auth = request.scope.get("abm_auth")
            if isinstance(auth, RuntimeAuth):
                return auth
        return runtime_auth_var.get()

    async def _call_authenticated_tool(
        self,
        name: str,
        args: dict[str, Any],
        ctx: Any,
    ) -> types.CallToolResult:
        auth = self._auth_from_ctx(ctx)
        if auth is None:
            return _error_result(
                code="ABM_INVALID_TOKEN",
                message="Missing MCP runtime credential.",
                action="reauthenticate",
            )
        async with self.database.sessions() as db:
            current_user = await db.get(User, auth.user.id)
        if current_user is None or current_user.status != UserStatus.ACTIVE:
            return _error_result(
                code="ABM_ACCOUNT_DISABLED",
                message="Account is disabled or does not exist.",
                action="reauthenticate",
            )
        # Keep authorization decisions on the current role and status even if
        # the MCP session outlives an administrator change.
        auth = replace(auth, user=current_user)
        if name not in TOOL_BY_NAME:
            return _error_result(
                code="ABM_TOOL_NOT_FOUND",
                message=f"Unknown tool: {name}",
            )
        try:
            if name == "account_register":
                return await self._account_register(args)
            if name in ADMIN_TOOL_BY_NAME:
                self._require_admin(auth)
                read_only_admin = {
                    "admin_list_users",
                    "admin_get_settings",
                    "admin_list_audit",
                }
                admin_scope = ACCOUNT_READ if name in read_only_admin else ACCOUNT_WRITE
                self._require_scope(auth, admin_scope)
                return await self._call_admin_tool(name, args, auth)
            if name in {"account_me", "api_key_list"}:
                self._require_scope(auth, ACCOUNT_READ)
                return await self._call_account_tool(name, args, auth, ctx)
            if name in {
                "account_update_profile",
                "account_change_password",
                "api_key_create",
                "api_key_revoke",
            }:
                self._require_scope(auth, ACCOUNT_WRITE)
                return await self._call_account_tool(name, args, auth)
            self._require_scope(auth, BROWSER)
            return await self._call_browser_tool(name, args, auth, ctx)
        except ApiError as exc:
            return _api_error_result(exc)
        except GatewayCallError as exc:
            return _gateway_error_result(exc)
        except (ValidationError, ValueError) as exc:
            return _validation_error_result(exc)
        except Exception:
            logger.exception("MCP tool failed: %s", name)
            return _error_result(
                code="ABM_INTERNAL_ERROR",
                message="Tool execution failed.",
                retryable=True,
                action="wait",
            )

    def _require_scope(self, auth: RuntimeAuth, scope: str) -> None:
        if scope not in auth.scopes:
            raise ApiError(
                403,
                "ABM_SCOPE_REQUIRED",
                f"The current OAuth grant is missing the {scope} scope. Reauthorize and try again.",
                action="reauthenticate",
            )

    def _require_admin(self, auth: RuntimeAuth) -> None:
        if auth.user.role != UserRole.ADMIN:
            raise ApiError(403, "ABM_ADMIN_REQUIRED", "Administrator account required.")

    async def _account_register(self, args: dict[str, Any]) -> types.CallToolResult:
        payload = RegisterRequest(
            email=str(args.get("email") or ""),
            password=str(args.get("password") or ""),
            display_name=str(args.get("displayName") or ""),
            application_note=args.get("applicationNote"),
        )
        async with self.database.sessions() as db:
            approval = bool(
                await get_setting(
                    db,
                    REGISTRATION_APPROVAL_SETTING,
                    self.settings.registration_require_approval,
                )
            )
            await register_user(
                db,
                email=str(payload.email),
                password=payload.password,
                display_name=payload.display_name,
                application_note=payload.application_note,
                registration_require_approval=approval,
            )
            await db.commit()
        return _json_result(
            {
                "status": "accepted",
                "message": (
                    "Registration request submitted. If approval is enabled, "
                    "wait for an administrator."
                ),
            }
        )

    async def _call_account_tool(
        self,
        name: str,
        args: dict[str, Any],
        auth: RuntimeAuth,
        ctx: Any = None,
    ) -> types.CallToolResult:
        if name == "account_me":
            return await self._account_me(auth, ctx)
        if name == "account_update_profile":
            return await self._account_update_profile(args, auth)
        if name == "account_change_password":
            return await self._account_change_password(args, auth)
        if name == "api_key_list":
            return await self._api_key_list(auth)
        if name == "api_key_create":
            return await self._api_key_create(args, auth)
        if name == "api_key_revoke":
            return await self._api_key_revoke(args, auth)
        raise ApiError(404, "ABM_TOOL_NOT_FOUND", f"Unknown account tool: {name}")

    async def _account_me(self, auth: RuntimeAuth, ctx: Any = None) -> types.CallToolResult:
        async with self.database.sessions() as db:
            user = await db.get(User, auth.user.id)
            if user is None:
                raise ApiError(404, "ABM_NOT_FOUND", "Account not found.")
            count = await active_key_count(db, user.id)
            limit = key_limit_for_user(user, self.settings)
        session_id = self._current_mcp_session_id(ctx)
        connected_key = (
            self.gateway.lease_for_session(auth.user.id, session_id)
            if session_id is not None
            else None
        )
        if connected_key is None:
            connected_key = self.gateway.connected_key_for_user(auth.user.id)
        return _json_result(
            {
                "user": _user_payload(user, self.settings),
                "effectivePlan": tier_for(user, self.settings),
                "activeApiKeyCount": count,
                "apiKeyLimit": limit,
                "extensionConnected": connected_key is not None,
                "connectedApiKeyId": connected_key,
                "authKind": auth.auth_kind,
                "scopes": list(auth.scopes),
            }
        )

    async def _account_update_profile(
        self,
        args: dict[str, Any],
        auth: RuntimeAuth,
    ) -> types.CallToolResult:
        display_name = args.get("displayName")
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("displayName must be a non-empty string.")
        display_name = display_name.strip()
        if len(display_name) > 120:
            raise ValueError("displayName must not exceed 120 characters.")
        async with self.database.sessions() as db:
            user = await db.get(User, auth.user.id)
            if user is None:
                raise ApiError(404, "ABM_NOT_FOUND", "Account not found.")
            user.display_name = display_name
            user.updated_at = utcnow()
            record_audit(
                db,
                event_type="ABM_ACCOUNT_PROFILE_UPDATED",
                actor_user_id=user.id,
                subject_user_id=user.id,
                metadata={"displayName": display_name},
            )
            await db.commit()
            await db.refresh(user)
            return _json_result({"user": _user_payload(user, self.settings)})

    async def _account_change_password(
        self,
        args: dict[str, Any],
        auth: RuntimeAuth,
    ) -> types.CallToolResult:
        current = args.get("currentPassword")
        new = args.get("newPassword")
        if not isinstance(current, str) or not current:
            raise ValueError("currentPassword must be a non-empty string.")
        if not isinstance(new, str) or len(new) < self.settings.password_min_length:
            raise ValueError(
                f"newPassword must be at least {self.settings.password_min_length} characters."
            )
        async with self.database.sessions() as db:
            user = await db.get(User, auth.user.id)
            if user is None:
                raise ApiError(404, "ABM_NOT_FOUND", "Account not found.")
            if not verify_password(current, user.password_hash):
                raise ApiError(
                    400, "ABM_INVALID_CURRENT_PASSWORD", "Current password is incorrect."
                )
            user.password_hash = hash_password(new)
            user.updated_at = utcnow()
            await revoke_user_sessions(db, user_id=user.id)
            await self.oauth.revoke_user_tokens(
                db,
                user_id=user.id,
                except_token_id=auth.access_token_id,
            )
            record_audit(
                db,
                event_type="ABM_ACCOUNT_PASSWORD_CHANGED",
                actor_user_id=user.id,
                subject_user_id=user.id,
                metadata={},
            )
            await db.commit()
        return _json_result(
            {
                "status": "ok",
                "message": (
                    "Password changed. Other account sessions and OAuth credentials were revoked."
                ),
            }
        )

    async def _api_key_list(self, auth: RuntimeAuth) -> types.CallToolResult:
        async with self.database.sessions() as db:
            user = await db.get(User, auth.user.id)
            if user is None:
                raise ApiError(404, "ABM_NOT_FOUND", "Account not found.")
            rows = await list_user_api_keys(db, user.id)
            count = await active_key_count(db, user.id)
            limit = key_limit_for_user(user, self.settings)
        return _json_result(
            {
                "items": [_api_key_payload(row) for row in rows],
                "activeCount": count,
                "limit": limit,
            }
        )

    async def _api_key_create(
        self,
        args: dict[str, Any],
        auth: RuntimeAuth,
    ) -> types.CallToolResult:
        name = args.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string.")
        name = name.strip()
        if len(name) > 120:
            raise ValueError("name must not exceed 120 characters.")
        async with self.key_locks.hold(auth.user.id), self.database.sessions() as db:
            user = await db.get(User, auth.user.id)
            if user is None:
                raise ApiError(404, "ABM_NOT_FOUND", "Account not found.")
            key, plaintext = await create_api_key(
                db,
                user=user,
                name=name,
                settings=self.settings,
            )
            await db.commit()
            await db.refresh(key)
            return _json_result(
                {
                    "apiKey": _api_key_payload(key, plaintext=plaintext),
                    "message": (
                        "The API Key secret is returned only in this response. Store it now."
                    ),
                }
            )

    async def _api_key_revoke(
        self,
        args: dict[str, Any],
        auth: RuntimeAuth,
    ) -> types.CallToolResult:
        key_id = args.get("keyId")
        if not isinstance(key_id, str) or not key_id:
            raise ValueError("keyId must be a non-empty string.")
        async with self.database.sessions() as db:
            user = await db.get(User, auth.user.id)
            if user is None:
                raise ApiError(404, "ABM_NOT_FOUND", "Account not found.")
            key = await revoke_api_key(db, user=user, key_id=key_id)
            await db.commit()
        await self.gateway.close_for_key(
            key.id,
            SessionError(
                "ABM_API_KEY_REVOKED",
                "API Key revoked.",
                1008,
                action="open_account_portal",
            ),
        )
        return _json_result({"status": "revoked", "id": key.id})

    async def _call_admin_tool(
        self,
        name: str,
        args: dict[str, Any],
        auth: RuntimeAuth,
    ) -> types.CallToolResult:
        try:
            from abm_cloud.mcp import call_admin_tool
        except ImportError as exc:
            raise ApiError(
                404,
                "ABM_TOOL_NOT_FOUND",
                "Administrator tools are not available on this server.",
            ) from exc
        return await call_admin_tool(self, name, args, auth)

    async def _maybe_alert_usage(
        self,
        auth: RuntimeAuth,
        api_key_id: str,
    ) -> None:
        try:
            threshold = await self.usage.crossed_thresholds(
                user_id=auth.user.id,
                api_key_id=api_key_id,
                plan=tier_for(auth.user, self.settings),
                settings=self.settings,
            )
        except Exception:
            logger.exception("Failed to evaluate usage alerts")
            return
        if threshold is None:
            return
        try:
            totals = await self.usage.current_month_totals(
                user_id=auth.user.id,
                api_key_id=api_key_id,
            )
        except Exception:
            logger.exception("Failed to load usage totals for alert")
            totals = {}
        plan = tier_for(auth.user, self.settings)
        base_url = (
            self.settings.public_base_url.strip().rstrip("/")
            or f"http://127.0.0.1:{self.settings.port}"
        )
        console_url = f"{base_url}/console"
        try:
            await self.notifications.create(
                user_id=auth.user.id,
                kind="usage",
                title=f"Usage reached {threshold}%",
                body=(
                    f"Your {plan} plan has reached {threshold}% of a monthly quota. "
                    "Review usage in the console."
                ),
                action_url=console_url,
            )
        except Exception:
            logger.exception("Failed to create usage notice")
        try:
            await self.gateway.send_notice(
                api_key_id=api_key_id,
                notice_id=f"usage_{api_key_id}_{threshold}",
                title=f"ABM usage at {threshold}%",
                level="warning",
                body=(
                    f"Your {plan} plan has reached {threshold}% of a monthly quota. "
                    "Review usage in the console."
                ),
                action_url=console_url,
            )
        except Exception:
            logger.exception("Failed to push usage notice to extension")
        try:
            await self.email.send_usage_alert(
                to=auth.user.email,
                threshold=threshold,
                plan=plan,
                totals=totals,
                console_url=console_url,
            )
        except Exception:
            logger.exception("Failed to send usage alert email")
        if self.settings.alert_webhook_url:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        self.settings.alert_webhook_url,
                        json={
                            "event": "usage.threshold",
                            "threshold": threshold,
                            "plan": plan,
                            "userId": auth.user.id,
                            "apiKeyId": api_key_id,
                            "totals": totals,
                            "consoleUrl": console_url,
                            "at": datetime.now(UTC).isoformat(),
                        },
                    )
            except Exception:
                logger.exception("Failed to send usage alert webhook")

    async def _call_browser_tool(
        self,
        name: str,
        args: dict[str, Any],
        auth: RuntimeAuth,
        ctx: Any = None,
    ) -> types.CallToolResult:
        if name == "browser_open_session":
            return await self._open_browser_session(auth, args)
        if name == "browser_close_session":
            return await self._close_browser_session(auth, args)

        browser_session_id = args.get("browserSessionId")
        if browser_session_id is not None:
            if not isinstance(browser_session_id, str) or not browser_session_id:
                raise GatewayCallError("ABM_VALIDATION_ERROR", "browserSessionId is invalid.")
            connection_id = await self.gateway.touch_session(
                auth.user.id,
                browser_session_id,
            )
            if connection_id is None:
                raise GatewayCallError(
                    "ABM_BROWSER_SESSION_INVALID",
                    "browserSessionId does not exist, has expired, or its connection is offline.",
                    retryable=True,
                    action="wait",
                )
            api_key_id = self.gateway.api_key_for_connection(connection_id)
            preferred, allowed = self._connection_policy(auth)
            if api_key_id is None:
                raise GatewayCallError(
                    "ABM_CONNECTION_FORBIDDEN",
                    "The browser connection is no longer available.",
                    action="reauthenticate",
                )
            if preferred is not None and api_key_id != preferred:
                raise GatewayCallError(
                    "ABM_CONNECTION_FORBIDDEN",
                    "This connection is not included in the current OAuth grant.",
                    action="reauthenticate",
                )
            if allowed is not None and api_key_id not in allowed:
                raise GatewayCallError(
                    "ABM_CONNECTION_FORBIDDEN",
                    "This connection is not included in the current OAuth grant.",
                    action="reauthenticate",
                )
        else:
            connection_id = await self._gateway_connection_id(auth, ctx)
            api_key_id = self.gateway.api_key_for_connection(connection_id)
            if api_key_id is None:
                raise GatewayCallError(
                    "ABM_EXTENSION_OFFLINE",
                    "The browser connection closed before the tool call.",
                    retryable=True,
                    action="wait",
                )

        try:
            exceeded = await self.usage.exceeded_metrics(
                user_id=auth.user.id,
                api_key_id=api_key_id,
                plan=tier_for(auth.user, self.settings),
                settings=self.settings,
            )
        except Exception:
            logger.exception("Failed to check usage quota")
            exceeded = []
        if "tool_calls" in exceeded or (
            name == "browser_stage_video"
            and ("video_bytes" in exceeded or "video_jobs" in exceeded)
        ):
            raise GatewayCallError(
                "ABM_QUOTA_EXCEEDED",
                "Monthly quota exceeded. Open the account console to review usage.",
                retryable=False,
                action="open_account_portal",
            )

        try:
            await self.usage.record_tool_call(
                user_id=auth.user.id,
                api_key_id=api_key_id,
            )
        except Exception:
            logger.exception("Failed to record tool usage")
        await self._maybe_alert_usage(auth, api_key_id)

        if name == "browser_send_notice":
            title = args.get("title")
            if not isinstance(title, str) or not title:
                raise GatewayCallError(
                    "ABM_VALIDATION_ERROR",
                    "title must be a non-empty string.",
                )
            sent = await self.gateway.send_notice(
                api_key_id=api_key_id,
                notice_id=str(args.get("id") or f"notice_{uuid4().hex}"),
                title=title,
                level=str(args.get("level") or "info"),
                body=args.get("body"),
                action_url=args.get("actionUrl"),
            )
            return _json_result({"sent": 1 if sent else 0})
        if name == "browser_stage_video":
            try:
                result = await self.video.stage(
                    api_key_id=api_key_id,
                    file_name=str(args.get("fileName") or ""),
                    file_type=args.get("fileType"),
                    base64_data=args.get("base64"),
                    url=args.get("url"),
                    delivery=args.get("delivery"),
                    timeout_ms=args.get("timeoutMs"),
                )
            except VideoError as exc:
                raise GatewayCallError(
                    exc.code,
                    exc.message,
                    retryable=exc.retryable,
                    action=exc.action,
                ) from exc
            try:
                await self.usage.record_video(
                    user_id=auth.user.id,
                    api_key_id=api_key_id,
                    relayed_bytes=int(result.get("relayedBytes") or 0),
                )
            except Exception:
                logger.exception("Failed to record video usage")
            await self._maybe_alert_usage(auth, api_key_id)
            return _json_result(result)
        extension_args = {key: value for key, value in args.items() if key != "browserSessionId"}
        context = (
            self.gateway.session_context(auth.user.id, browser_session_id)
            if browser_session_id
            else None
        )
        result = await self.gateway.call_tool(
            connection_id=connection_id,
            name=name,
            arguments=extension_args,
            context=context,
        )
        return _normalize_extension_result(result)

    def _current_mcp_session_id(self, ctx: Any = None) -> str | None:
        """Return the current MCP transport session id, when one exists."""
        request = getattr(ctx, "request", None)
        if request is not None:
            session_id = request.headers.get("mcp-session-id")
            if session_id:
                return session_id
        context = request_context_var.get() or {}
        return context.get("mcp_session_id")

    def _connection_policy(
        self,
        auth: RuntimeAuth,
    ) -> tuple[str | None, set[str] | None]:
        if auth.api_key is not None:
            return auth.api_key.id, None
        if auth.connection_mode == "pinned":
            if len(auth.connection_ids) != 1:
                raise GatewayCallError(
                    "ABM_CONNECTION_FORBIDDEN",
                    "The OAuth grant is not bound to a valid browser connection. "
                    "Reauthorize and try again.",
                    action="reauthenticate",
                )
            return auth.connection_ids[0], None
        if auth.connection_mode == "pool":
            return None, set(auth.connection_ids)
        return None, None

    async def _open_browser_session(
        self,
        auth: RuntimeAuth,
        args: dict[str, Any],
    ) -> types.CallToolResult:
        preferred, allowed = self._connection_policy(auth)
        requested = args.get("connectionId")
        requested_connection_id: str | None = None
        if requested is not None:
            if not isinstance(requested, str) or not requested:
                raise GatewayCallError("ABM_VALIDATION_ERROR", "connectionId is invalid.")
            peer = self.gateway.get_peer(requested)
            if peer is None or peer.user_id != auth.user.id:
                raise GatewayCallError(
                    "ABM_EXTENSION_OFFLINE",
                    "The selected browser connection is offline.",
                    retryable=True,
                    action="open_extension",
                )
            if allowed is not None and peer.api_key_id not in allowed:
                raise GatewayCallError(
                    "ABM_CONNECTION_FORBIDDEN",
                    "This connection is not included in the current OAuth grant.",
                    action="reauthenticate",
                )
            if auth.connection_mode == "pinned" and preferred != peer.api_key_id:
                raise GatewayCallError(
                    "ABM_CONNECTION_FORBIDDEN",
                    "This connection is not included in the current OAuth grant.",
                    action="reauthenticate",
                )
            requested_connection_id = peer.connection_id
        browser_session_id = f"bs_{secrets.token_urlsafe(24)}"
        ttl_seconds = args.get("ttlSeconds")
        if ttl_seconds is not None and not isinstance(ttl_seconds, int):
            raise GatewayCallError("ABM_VALIDATION_ERROR", "ttlSeconds must be an integer.")
        group_title = args.get("groupTitle")
        if group_title is not None and not isinstance(group_title, str):
            raise GatewayCallError("ABM_VALIDATION_ERROR", "groupTitle must be a string.")
        collapsed = args.get("collapsed")
        if collapsed is not None and not isinstance(collapsed, bool):
            raise GatewayCallError("ABM_VALIDATION_ERROR", "collapsed must be a boolean.")
        priority = args.get("priority")
        if priority is not None and not isinstance(priority, int):
            raise GatewayCallError("ABM_VALIDATION_ERROR", "priority must be an integer.")
        connection_id = await self.gateway.acquire_connection_for_session(
            user_id=auth.user.id,
            session_id=browser_session_id,
            preferred_api_key_id=None if requested_connection_id else preferred,
            allowed_api_key_ids=allowed,
            preferred_connection_id=requested_connection_id,
            ttl_seconds=ttl_seconds,
            group_title=group_title,
            collapsed=collapsed,
            priority=priority or 0,
        )
        peer = self.gateway.get_peer(connection_id)
        return _json_result(
            {
                "browserSessionId": browser_session_id,
                "connectionId": connection_id,
                "apiKeyId": peer.api_key_id if peer else None,
                "browserId": peer.browser_id if peer else None,
                "capabilities": peer.capabilities if peer else {},
                "groupTitle": group_title,
                "collapsed": collapsed,
            }
        )

    async def _close_browser_session(
        self,
        auth: RuntimeAuth,
        args: dict[str, Any],
    ) -> types.CallToolResult:
        browser_session_id = args.get("browserSessionId")
        if not isinstance(browser_session_id, str) or not browser_session_id:
            raise GatewayCallError("ABM_VALIDATION_ERROR", "browserSessionId must not be empty.")
        context = self.gateway.session_context(auth.user.id, browser_session_id)
        if context is not None:
            try:
                await self.gateway.call_tool(
                    connection_id=context["connectionId"],
                    name="browser_control",
                    arguments={"action": "close_group", "params": {}},
                    context=context,
                )
            except GatewayCallError:
                logger.debug("Failed to close task tab group", exc_info=True)
        await self.gateway.release_session(auth.user.id, browser_session_id)
        return _json_result({"closed": True})

    async def _gateway_connection_id(self, auth: RuntimeAuth, ctx: Any = None) -> str:
        session_id = self._current_mcp_session_id(ctx)
        preferred_api_key_id, allowed_api_key_ids = self._connection_policy(auth)

        if session_id:
            return await self.gateway.acquire_connection_for_session(
                user_id=auth.user.id,
                session_id=session_id,
                preferred_api_key_id=preferred_api_key_id,
                allowed_api_key_ids=allowed_api_key_ids,
            )

        if auth.auth_kind == "oauth" and auth.connection_mode in {"auto", "pool"}:
            raise GatewayCallError(
                "ABM_BROWSER_SESSION_REQUIRED",
                "The current OAuth grant can use multiple browsers. "
                "Call browser_open_session first.",
                retryable=False,
                action="open_browser_session",
            )
        connections = [
            peer
            for peer in self.gateway.connections_for_user(auth.user.id)
            if allowed_api_key_ids is None or peer.api_key_id in allowed_api_key_ids
        ]
        if preferred_api_key_id is not None:
            connections = [peer for peer in connections if peer.api_key_id == preferred_api_key_id]
        if not connections:
            raise GatewayCallError(
                "ABM_EXTENSION_OFFLINE",
                "No online browser extension is available for the current account. "
                "Configure an API Key in the extension and connect it first.",
                retryable=True,
                action="open_extension",
            )
        connections.sort(key=lambda peer: peer.last_seen, reverse=True)
        return connections[0].connection_id
