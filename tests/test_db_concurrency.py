from __future__ import annotations

import asyncio
from datetime import timedelta

from starlette.requests import Request

from abm_server.accounts import create_account_session
from abm_server.auth.dependencies import SESSION_COOKIE, get_current_auth
from abm_server.config import Settings
from abm_server.creation.publish import create_publication, open_publication
from abm_server.creation.service import create_asset, create_project
from abm_server.database import Database
from abm_server.models import Setting, User, utcnow


def _settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'concurrency.db'}",
        session_cookie_secure=False,
        bootstrap_admin_email=None,
        bootstrap_admin_password=None,
    )


async def _seed_user(session, email: str = "lock@example.com") -> User:
    user = User(
        email=email,
        display_name="Lock Test",
        password_hash="x",
        status="active",
    )
    session.add(user)
    await session.flush()
    return user


def _request_with_session(token: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", f"{SESSION_COOKIE}={token}".encode())],
        }
    )


def test_auth_touch_does_not_hold_the_sqlite_write_lock(tmp_path) -> None:
    """Touching last_seen_at must not keep a write transaction open.

    A pending UPDATE blocks every other SQLite writer until the request ends,
    which surfaced as `database is locked` -> HTTP 500 on unrelated endpoints
    such as resuming a research job.
    """

    async def scenario() -> None:
        database = Database(_settings(tmp_path))
        await database.create_schema()
        async with database.sessions() as session:
            user = await _seed_user(session)
            account_session, token, _csrf = await create_account_session(
                session,
                user=user,
                settings=_settings(tmp_path),
                user_agent=None,
                ip_address=None,
            )
            account_session.last_seen_at = utcnow() - timedelta(minutes=30)
            await session.commit()

            request = _request_with_session(token)
            auth = await get_current_auth(request=request, db=session)
            assert auth.user.email == "lock@example.com"
            assert not session.in_transaction(), "auth left an open transaction"

            async def concurrent_write() -> None:
                async with database.sessions() as other:
                    other.add(Setting(key="concurrency-probe", value={"ok": True}))
                    await other.commit()

            await asyncio.wait_for(concurrent_write(), timeout=3)
        await database.dispose()

    asyncio.run(scenario())


def test_publish_open_releases_the_write_lock_before_browser_work(tmp_path) -> None:
    """Publishing must commit the "opening" state before the browser call."""

    async def scenario() -> None:
        database = Database(_settings(tmp_path))
        await database.create_schema()
        async with database.sessions() as session:
            user = await _seed_user(session)
            project = await create_project(session, user, title="Publish project")
            asset = await create_asset(
                session,
                user,
                title="Publish asset",
                project_id=project.id,
                content_md="# Body",
            )
            await session.commit()
            publication = await create_publication(
                session, user, asset_id=asset.id, platform="zhihu"
            )
            await session.commit()

            class Gateway:
                async def acquire_connection_for_session(self, **_kwargs):
                    assert not session.in_transaction(), (
                        "publish held the write lock while opening the browser"
                    )
                    return "conn_test"

                def session_context(self, *_args, **_kwargs):
                    return None

                async def call_tool(self, **_kwargs):
                    assert not session.in_transaction()
                    return {"ok": True}

                async def release_session(self, *_args, **_kwargs) -> None:
                    return None

            result = await open_publication(session, Gateway(), user, publication)
            await session.commit()
            assert result.status == "ready"
        await database.dispose()

    asyncio.run(scenario())
