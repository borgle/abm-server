from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import __version__
from .accounts import cleanup_account_sessions, initialize_identity_state
from .api import api_router
from .concurrency import KeyedLockPool, SlidingWindowLimiter
from .config import Settings, get_settings
from .creation.research.runner import ResearchRunner
from .database import Database
from .editions import resolve_edition
from .email import EmailService
from .errors import install_error_handlers
from .extension_gateway import ExtensionGateway
from .logging import configure_logging
from .mcp import McpPathMiddleware, McpService
from .notices import NotificationService
from .storage import build_storage
from .system_config import apply_overrides, capture_base, load_overrides
from .usage import UsageService
from .video import VideoService
from .web import router as web_router

logger = logging.getLogger(__name__)


class _RevalidatingStaticFiles(StaticFiles):
    """Serve assets with ``no-cache`` so edits are visible without a deploy.

    ``asset_version`` only decorates the top-level script tags; nested module
    imports (for example ``./workspace-i18n.js``) keep the bare path and would
    otherwise stay stale in the browser cache until it expires.
    """

    async def get_response(self, path: str, scope):  # noqa: ANN001 - Starlette signature
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


async def _session_cleanup_loop(database: Database, settings: Settings) -> None:
    """Prune expired sign-in sessions once a day (their IP is retained metadata)."""

    while True:
        try:
            removed = await cleanup_account_sessions(
                database,
                retention_days=settings.session_retention_days,
            )
            if removed:
                logger.info("Pruned %s expired account sessions", removed)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("Account session cleanup failed")
        await asyncio.sleep(12 * 60 * 60)


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    edition = resolve_edition(app_settings.edition)
    if not edition.multi_user:
        # The single-user edition has exactly one account; social sign-up would
        # bypass that rule, so it is disabled at startup.
        app_settings.social_login_enabled = False
    app_database = database or Database(app_settings)
    extension_gateway = ExtensionGateway(app_database, app_settings)
    video_service = VideoService(extension_gateway, app_settings)
    research_runner = ResearchRunner(app_database, extension_gateway, app_settings)
    usage_service = UsageService(app_database)
    email_service = EmailService(app_settings)
    notification_service = NotificationService(app_database)
    mcp_service = McpService(
        app_database,
        extension_gateway,
        video_service,
        app_settings,
        usage=usage_service,
        email=email_service,
        notifications=notification_service,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        configure_logging(app_settings.log_level)
        app_settings.ensure_sqlite_directory()
        logger.info("Starting ABM（a browser mcp） server %s", __version__)
        async with app_database.sessions() as session:
            await initialize_identity_state(session, app_settings)
            try:
                app.state.config_base = capture_base(app_settings)
                apply_overrides(
                    app_settings,
                    await load_overrides(session),
                    app.state.config_base,
                )
            except Exception:
                logger.warning("System configuration overrides are unavailable", exc_info=True)
        async with mcp_service.run():
            await video_service.start()
            await research_runner.mark_interrupted()
            await research_runner.start()
            session_cleanup = asyncio.create_task(_session_cleanup_loop(app_database, app_settings))
            try:
                yield
            finally:
                session_cleanup.cancel()
                with suppress(asyncio.CancelledError):
                    await session_cleanup
                await research_runner.shutdown()
                await video_service.shutdown()
                await extension_gateway.shutdown()
        await app_database.dispose()

    app = FastAPI(
        title="ABM（a browser mcp） Server",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.database = app_database
    app.state.edition = edition
    app.state.storage = build_storage(app_settings)
    app.state.extension_gateway = extension_gateway
    app.state.video_service = video_service
    app.state.research_runner = research_runner
    app.state.usage_service = usage_service
    app.state.email_service = email_service
    app.state.notification_service = notification_service
    app.state.mcp_service = mcp_service
    app.state.oauth_service = mcp_service.oauth
    app.state.registration_limiter = SlidingWindowLimiter()
    app.state.login_limiter = SlidingWindowLimiter()
    app.state.key_locks = KeyedLockPool()
    install_error_handlers(app)
    app.router.routes.extend(mcp_service.oauth.routes)
    app.add_middleware(
        McpPathMiddleware,
        mcp_app=mcp_service.asgi,
        public_mcp_app=mcp_service.public_asgi,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        # HTML pages are server-rendered per request; letting a browser reuse a
        # cached copy hides new markup (and its i18n keys) after a deploy.
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, object]:
        return {
            "ok": True,
            "service": "abm-browser-mcp",
            "version": __version__,
        }

    @app.get("/readyz", tags=["system"])
    async def readyz(request: Request) -> JSONResponse:
        database_state: Database = request.app.state.database
        try:
            async with database_state.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            logger.exception("Readiness check failed")
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "service": "abm-browser-mcp",
                    "error": {
                        "code": "ABM_DATABASE_UNAVAILABLE",
                        "message": str(exc),
                    },
                },
            )
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "service": "abm-browser-mcp",
                "version": __version__,
            },
        )

    app.include_router(api_router)
    app.include_router(web_router)
    app.mount(
        "/static",
        _RevalidatingStaticFiles(directory=Path(__file__).parent / "web" / "static"),
        name="static",
    )
    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "abm_server.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


if __name__ == "__main__":
    run()
