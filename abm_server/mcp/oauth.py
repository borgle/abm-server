from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.metadata import MetadataHandler, ProtectedResourceMetadataHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
)
from mcp.server.auth.routes import cors_middleware, validate_issuer_url
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from pydantic import AnyHttpUrl, AnyUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..accounts import as_utc
from ..audit import record_audit
from ..auth.scopes import ALL_SCOPES, DEFAULT_SCOPES
from ..auth.security import digest_token
from ..concurrency import SlidingWindowLimiter
from ..config import Settings
from ..database import Database
from ..errors import ApiError
from ..models import (
    ApiKey,
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthPendingAuthorization,
    OAuthRefreshToken,
    User,
    UserStatus,
    utcnow,
)

OAUTH_SCOPE_DESCRIPTIONS = {
    "browser": "通过浏览器扩展执行浏览器工具",
    "account:read": "读取账号、套餐和 API Key 元数据",
    "account:write": "创建和吊销 API Key、修改账号设置",
}


@dataclass(slots=True)
class PendingAuthorization:
    id: str
    client_id: str
    client_name: str
    scopes: list[str]
    redirect_uri: str
    state: str | None
    expires_at: datetime


def _timestamp(value: datetime) -> float:
    value = as_utc(value) or utcnow()
    return value.timestamp()


def _append_query(uri: str, params: dict[str, str | None]) -> str:
    parsed = urlsplit(uri)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value is not None)
    return urlunsplit(parsed._replace(query=urlencode(query)))


class OAuthProvider(OAuthAuthorizationServerProvider[Any, Any, Any]):
    def __init__(self, service: OAuthService):
        self.service = service

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with self.service.database.sessions() as session:
            row = await session.get(OAuthClient, client_id)
            return self.service.client_info(row) if row is not None else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise ValueError("client_id is required")
        async with self.service.database.sessions() as session:
            row = await session.get(OAuthClient, client_info.client_id)
            if row is None:
                row = OAuthClient(client_id=client_info.client_id)
                session.add(row)
            row.client_name = client_info.client_name
            row.client_uri = str(client_info.client_uri) if client_info.client_uri else None
            row.logo_uri = str(client_info.logo_uri) if client_info.logo_uri else None
            row.redirect_uris = [str(uri) for uri in client_info.redirect_uris or []]
            row.grant_types = list(client_info.grant_types)
            row.response_types = list(client_info.response_types)
            row.scope = client_info.scope
            row.token_endpoint_auth_method = client_info.token_endpoint_auth_method or "none"
            await session.commit()

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        async with self.service.database.sessions() as session:
            pending = OAuthPendingAuthorization(
                client_id=client.client_id or "",
                redirect_uri=str(params.redirect_uri),
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                code_challenge=params.code_challenge,
                scopes=params.scopes or list(DEFAULT_SCOPES),
                state=params.state,
                resource=params.resource,
                expires_at=utcnow()
                + timedelta(seconds=self.service.settings.oauth_pending_ttl_seconds),
            )
            session.add(pending)
            await session.commit()
            return f"{self.service.issuer_url}/oauth/authorize?request_id={pending.id}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        async with self.service.database.sessions() as session:
            row = await session.scalar(
                select(OAuthAuthorizationCode).where(
                    OAuthAuthorizationCode.code_hash == digest_token(authorization_code)
                )
            )
            if row is None or row.client_id != client.client_id or row.used_at is not None:
                return None
            return AuthorizationCode(
                code=authorization_code,
                scopes=list(row.scopes),
                expires_at=_timestamp(row.expires_at),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=AnyUrl(row.redirect_uri),
                redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
                resource=row.resource,
                subject=row.user_id,
            )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        async with self.service.database.sessions() as session:
            row = await session.scalar(
                select(OAuthAuthorizationCode).where(
                    OAuthAuthorizationCode.code_hash == digest_token(authorization_code.code)
                )
            )
            if row is None or row.used_at is not None:
                raise TokenError("invalid_grant", "authorization code does not exist")
            if (as_utc(row.expires_at) or utcnow()) < utcnow():
                raise TokenError("invalid_grant", "authorization code has expired")
            row.used_at = utcnow()
            tokens = await self.service.issue_tokens(
                session,
                client_id=row.client_id,
                user_id=row.user_id,
                scopes=list(row.scopes),
                resource=row.resource,
                connection_mode=row.connection_mode,
                connection_ids=list(row.connection_ids),
            )
            await session.commit()
            return tokens

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        async with self.service.database.sessions() as session:
            row = await session.scalar(
                select(OAuthRefreshToken).where(
                    OAuthRefreshToken.token_hash == digest_token(refresh_token)
                )
            )
            if row is None or row.client_id != client.client_id or row.revoked_at is not None:
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=row.client_id,
                scopes=list(row.scopes),
                expires_at=int(_timestamp(row.expires_at)),
                subject=row.user_id,
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        async with self.service.database.sessions() as session:
            row = await session.scalar(
                select(OAuthRefreshToken).where(
                    OAuthRefreshToken.token_hash == digest_token(refresh_token.token)
                )
            )
            if row is None or row.revoked_at is not None:
                raise TokenError("invalid_grant", "refresh token does not exist")
            if (as_utc(row.expires_at) or utcnow()) < utcnow():
                raise TokenError("invalid_grant", "refresh token has expired")
            row.revoked_at = utcnow()
            tokens = await self.service.issue_tokens(
                session,
                client_id=row.client_id,
                user_id=row.user_id,
                scopes=scopes or list(row.scopes),
                resource=None,
                connection_mode=row.connection_mode,
                connection_ids=list(row.connection_ids),
            )
            await session.commit()
            return tokens

    async def load_access_token(self, token: str) -> AccessToken | None:
        async with self.service.database.sessions() as session:
            row = await session.scalar(
                select(OAuthAccessToken).where(OAuthAccessToken.token_hash == digest_token(token))
            )
            if row is None or row.revoked_at is not None:
                return None
            if (as_utc(row.expires_at) or utcnow()) < utcnow():
                return None
            user = await session.get(User, row.user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                return None
            return AccessToken(
                token=token,
                client_id=row.client_id,
                scopes=list(row.scopes),
                expires_at=int(_timestamp(row.expires_at)),
                resource=row.resource,
                subject=row.user_id,
                claims={
                    "user_id": row.user_id,
                    "token_id": row.id,
                    "connection_mode": row.connection_mode,
                    "connection_ids": list(row.connection_ids),
                },
            )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with self.service.database.sessions() as session:
            if isinstance(token, AccessToken):
                row = await session.scalar(
                    select(OAuthAccessToken).where(
                        OAuthAccessToken.token_hash == digest_token(token.token)
                    )
                )
            else:
                row = await session.scalar(
                    select(OAuthRefreshToken).where(
                        OAuthRefreshToken.token_hash == digest_token(token.token)
                    )
                )
            if row is not None and row.revoked_at is None:
                row.revoked_at = utcnow()
                await session.commit()


class OAuthService:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        raw_issuer = settings.oauth_issuer_url or settings.public_base_url
        if not raw_issuer:
            raw_issuer = f"http://127.0.0.1:{settings.port}"
        self.issuer_url = raw_issuer.rstrip("/")
        validate_issuer_url(AnyHttpUrl(self.issuer_url))
        if urlsplit(self.issuer_url).path not in {"", "/"}:
            raise ValueError(
                "OAuth issuer must contain only scheme and host, without a path. "
                "Use the origin from ABM_PUBLIC_BASE_URL."
            )
        self.provider = OAuthProvider(self)
        self.registration_limiter = SlidingWindowLimiter()
        self.routes = self._build_routes()

    @asynccontextmanager
    async def _session_scope(
        self,
        session: AsyncSession | None = None,
    ) -> AsyncIterator[AsyncSession]:
        if session is not None:
            yield session
            return
        async with self.database.sessions() as own_session:
            yield own_session

    @property
    def resource_metadata_url(self) -> str:
        return f"{self.issuer_url}/.well-known/oauth-protected-resource/mcp"

    @property
    def resource_url(self) -> str:
        return f"{self.issuer_url}/mcp"

    def client_info(self, row: OAuthClient) -> OAuthClientInformationFull:
        return OAuthClientInformationFull(
            client_id=row.client_id,
            client_name=row.client_name,
            client_uri=row.client_uri,
            logo_uri=row.logo_uri,
            redirect_uris=[AnyUrl(uri) for uri in row.redirect_uris],
            grant_types=list(row.grant_types),
            response_types=list(row.response_types),
            scope=row.scope,
            token_endpoint_auth_method=row.token_endpoint_auth_method,
        )

    async def issue_tokens(
        self,
        session: AsyncSession,
        *,
        client_id: str,
        user_id: str,
        scopes: list[str],
        resource: str | None,
        connection_mode: str = "auto",
        connection_ids: list[str] | None = None,
    ) -> OAuthToken:
        user = await session.get(User, user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise TokenError("invalid_grant", "Account does not exist or is not active.")
        connection_ids = list(connection_ids or [])
        now = utcnow()
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        access_expires = now + timedelta(seconds=self.settings.oauth_access_token_ttl_seconds)
        refresh_expires = now + timedelta(seconds=self.settings.oauth_refresh_token_ttl_seconds)
        session.add(
            OAuthAccessToken(
                token_hash=digest_token(access_token),
                client_id=client_id,
                user_id=user_id,
                scopes=scopes,
                connection_mode=connection_mode,
                connection_ids=connection_ids,
                resource=resource,
                expires_at=access_expires,
            )
        )
        session.add(
            OAuthRefreshToken(
                token_hash=digest_token(refresh_token),
                client_id=client_id,
                user_id=user_id,
                scopes=scopes,
                connection_mode=connection_mode,
                connection_ids=connection_ids,
                expires_at=refresh_expires,
            )
        )
        return OAuthToken(
            access_token=access_token,
            expires_in=self.settings.oauth_access_token_ttl_seconds,
            scope=" ".join(scopes),
            refresh_token=refresh_token,
        )

    async def get_pending_authorization(
        self,
        request_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> PendingAuthorization | None:
        async with self._session_scope(session) as db:
            row = await db.get(OAuthPendingAuthorization, request_id)
            if row is None or (as_utc(row.expires_at) or utcnow()) < utcnow():
                return None
            client = await db.get(OAuthClient, row.client_id)
            return PendingAuthorization(
                id=row.id,
                client_id=row.client_id,
                client_name=(client.client_name if client and client.client_name else "MCP client"),
                scopes=list(row.scopes),
                redirect_uri=row.redirect_uri,
                state=row.state,
                expires_at=row.expires_at,
            )

    async def approve_authorization(
        self,
        request_id: str,
        *,
        user: User,
        connection_mode: str = "auto",
        connection_ids: list[str] | None = None,
        session: AsyncSession | None = None,
    ) -> str:
        if connection_mode not in {"auto", "pinned", "pool"}:
            raise ApiError(400, "ABM_VALIDATION_ERROR", "connectionMode is invalid.")
        connection_ids = list(dict.fromkeys(connection_ids or []))
        async with self._session_scope(session) as db:
            row = await db.get(OAuthPendingAuthorization, request_id)
            if row is None or (as_utc(row.expires_at) or utcnow()) < utcnow():
                raise ApiError(
                    400,
                    "ABM_OAUTH_REQUEST_INVALID",
                    "Authorization request does not exist or has expired.",
                )
            if connection_mode in {"pinned", "pool"}:
                if connection_mode == "pinned" and len(connection_ids) != 1:
                    raise ApiError(
                        400, "ABM_VALIDATION_ERROR", "Pinned mode requires exactly one connection."
                    )
                allowed = set(
                    await db.scalars(
                        select(ApiKey.id).where(
                            ApiKey.user_id == user.id,
                            ApiKey.revoked_at.is_(None),
                            ApiKey.id.in_(connection_ids),
                        )
                    )
                )
                if len(allowed) != len(connection_ids):
                    raise ApiError(
                        400,
                        "ABM_VALIDATION_ERROR",
                        "A selected connection does not exist or is revoked.",
                    )
            code = secrets.token_urlsafe(32)
            db.add(
                OAuthAuthorizationCode(
                    code_hash=digest_token(code),
                    client_id=row.client_id,
                    user_id=user.id,
                    scopes=list(row.scopes),
                    connection_mode=connection_mode,
                    connection_ids=connection_ids,
                    code_challenge=row.code_challenge,
                    redirect_uri=row.redirect_uri,
                    redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
                    resource=row.resource,
                    expires_at=utcnow()
                    + timedelta(seconds=self.settings.oauth_authorization_code_ttl_seconds),
                )
            )
            await db.delete(row)
            record_audit(
                db,
                event_type="ABM_OAUTH_AUTHORIZED",
                actor_user_id=user.id,
                subject_user_id=user.id,
                metadata={
                    "clientId": row.client_id,
                    "scopes": list(row.scopes),
                    "connectionMode": connection_mode,
                    "connectionIds": connection_ids,
                },
            )
            await db.commit()
            return _append_query(
                row.redirect_uri,
                {"code": code, "state": row.state},
            )

    async def deny_authorization(
        self,
        request_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> str:
        async with self._session_scope(session) as db:
            row = await db.get(OAuthPendingAuthorization, request_id)
            if row is None:
                raise ApiError(
                    400,
                    "ABM_OAUTH_REQUEST_INVALID",
                    "Authorization request does not exist or has expired.",
                )
            await db.delete(row)
            await db.commit()
            return _append_query(
                row.redirect_uri,
                {"error": "access_denied", "state": row.state},
            )

    async def revoke_user_tokens(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        except_token_id: str | None = None,
    ) -> None:
        revoked_at = utcnow()
        for model in (OAuthAccessToken, OAuthRefreshToken):
            rows = (
                await session.scalars(
                    select(model).where(
                        model.user_id == user_id,
                        model.revoked_at.is_(None),
                    )
                )
            ).all()
            for row in rows:
                if except_token_id is not None and row.id == except_token_id:
                    continue
                row.revoked_at = revoked_at

    def _build_routes(self) -> list[Route]:
        metadata = self._metadata()
        protected_metadata = self._protected_resource_metadata()
        protected_handler = ProtectedResourceMetadataHandler(protected_metadata)

        async def register_client(request: Request) -> Response:
            client_ip = request.client.host if request.client else "unknown"
            retry_after = await self.registration_limiter.hit(
                f"oauth-register:{client_ip[:64]}",
                limit=20,
                window_seconds=15 * 60,
            )
            if retry_after:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "temporarily_unavailable",
                        "error_description": "Too many dynamic client registration requests.",
                    },
                    headers={"Retry-After": str(retry_after)},
                )
            try:
                payload = await request.json()
                metadata_input = OAuthClientMetadata.model_validate(payload)
            except Exception as exc:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_client_metadata",
                        "error_description": f"Invalid client metadata: {exc}",
                    },
                )
            redirect_uris = metadata_input.redirect_uris or []
            if not redirect_uris:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_redirect_uri",
                        "error_description": "At least one redirect_uri is required.",
                    },
                )
            for redirect_uri in redirect_uris:
                if redirect_uri.scheme == "http" and redirect_uri.host not in {
                    "127.0.0.1",
                    "localhost",
                    "::1",
                }:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": "invalid_redirect_uri",
                            "error_description": "Non-loopback redirect_uri values must use HTTPS.",
                        },
                    )
            requested_grant_types = set(metadata_input.grant_types)
            if not {"authorization_code", "refresh_token"}.issubset(requested_grant_types):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_client_metadata",
                        "error_description": (
                            "grant_types must include authorization_code and refresh_token"
                        ),
                    },
                )
            if "code" not in metadata_input.response_types:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_client_metadata",
                        "error_description": "response_types must include code",
                    },
                )
            requested_scope = metadata_input.scope or " ".join(DEFAULT_SCOPES)
            requested_scopes = set(requested_scope.split())
            invalid_scopes = requested_scopes - set(ALL_SCOPES)
            if invalid_scopes:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_client_metadata",
                        "error_description": "Unsupported scope: "
                        + ", ".join(sorted(invalid_scopes)),
                    },
                )
            client_info = OAuthClientInformationFull(
                client_id=uuid4().hex,
                client_name=metadata_input.client_name,
                client_uri=metadata_input.client_uri,
                logo_uri=metadata_input.logo_uri,
                redirect_uris=metadata_input.redirect_uris,
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                scope=" ".join(sorted(requested_scopes)),
                token_endpoint_auth_method="none",
            )
            await self.provider.register_client(client_info)
            return PydanticJSONResponse(content=client_info, status_code=201)

        async def revoke_token(request: Request) -> Response:
            try:
                form = await request.form()
            except Exception:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_request",
                        "error_description": (
                            "Request body must be application/x-www-form-urlencoded."
                        ),
                    },
                )
            client_id = form.get("client_id")
            token_value = form.get("token")
            if (
                not isinstance(client_id, str)
                or not client_id
                or not isinstance(token_value, str)
                or not token_value
            ):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_request",
                        "error_description": "client_id and token must not be empty.",
                    },
                )
            client = await self.provider.get_client(client_id)
            if client is None:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "unauthorized_client",
                        "error_description": "Unknown client_id.",
                    },
                )
            hint = form.get("token_type_hint")
            token: AccessToken | RefreshToken | None = None
            access_loader = self.provider.load_access_token
            refresh_loader = partial(self.provider.load_refresh_token, client)
            loaders = (
                [refresh_loader, access_loader]
                if hint == "refresh_token"
                else [access_loader, refresh_loader]
            )
            for loader in loaders:
                token = await loader(token_value)
                if token is not None:
                    break
            if token is not None and token.client_id == client.client_id:
                await self.provider.revoke_token(token)
            return Response(
                status_code=200,
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )

        return [
            Route(
                "/.well-known/oauth-authorization-server",
                endpoint=cors_middleware(
                    MetadataHandler(metadata).handle,
                    ["GET", "OPTIONS"],
                ),
                methods=["GET", "OPTIONS"],
            ),
            Route(
                "/.well-known/oauth-protected-resource/mcp",
                endpoint=cors_middleware(
                    protected_handler.handle,
                    ["GET", "OPTIONS"],
                ),
                methods=["GET", "OPTIONS"],
            ),
            Route(
                "/.well-known/oauth-protected-resource",
                endpoint=cors_middleware(
                    protected_handler.handle,
                    ["GET", "OPTIONS"],
                ),
                methods=["GET", "OPTIONS"],
            ),
            Route(
                "/authorize",
                endpoint=AuthorizationHandler(self.provider).handle,
                methods=["GET", "POST"],
            ),
            Route(
                "/token",
                endpoint=cors_middleware(
                    TokenHandler(
                        self.provider,
                        ClientAuthenticator(self.provider),
                    ).handle,
                    ["POST", "OPTIONS"],
                ),
                methods=["POST", "OPTIONS"],
            ),
            Route(
                "/register",
                endpoint=cors_middleware(register_client, ["POST", "OPTIONS"]),
                methods=["POST", "OPTIONS"],
            ),
            Route(
                "/revoke",
                endpoint=cors_middleware(revoke_token, ["POST", "OPTIONS"]),
                methods=["POST", "OPTIONS"],
            ),
        ]

    def _metadata(self) -> OAuthMetadata:
        issuer = AnyHttpUrl(self.issuer_url)
        return OAuthMetadata(
            issuer=issuer,
            authorization_endpoint=AnyHttpUrl(f"{self.issuer_url}/authorize"),
            token_endpoint=AnyHttpUrl(f"{self.issuer_url}/token"),
            registration_endpoint=AnyHttpUrl(f"{self.issuer_url}/register"),
            revocation_endpoint=AnyHttpUrl(f"{self.issuer_url}/revoke"),
            scopes_supported=list(ALL_SCOPES),
            response_types_supported=["code"],
            grant_types_supported=["authorization_code", "refresh_token"],
            token_endpoint_auth_methods_supported=["none"],
            revocation_endpoint_auth_methods_supported=["none"],
            code_challenge_methods_supported=["S256"],
            service_documentation=AnyHttpUrl(f"{self.issuer_url}/docs/mcp"),
        )

    def _protected_resource_metadata(self) -> ProtectedResourceMetadata:
        return ProtectedResourceMetadata(
            resource=AnyHttpUrl(self.resource_url),
            authorization_servers=[AnyHttpUrl(self.issuer_url)],
            scopes_supported=list(ALL_SCOPES),
            resource_name="ABM Browser MCP",
            resource_documentation=AnyHttpUrl(f"{self.issuer_url}/docs/mcp"),
        )
