from __future__ import annotations

import asyncio
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from abm_server.accounts import cleanup_account_sessions
from abm_server.database import Database
from abm_server.models import AccountAuditEvent, AccountSession, User, utcnow

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-password-123"


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200


def test_login_audit_records_client_ip(admin_client: TestClient, admin_database: Database) -> None:
    _login(admin_client)

    async def latest_login() -> dict:
        async with admin_database.sessions() as session:
            row = await session.scalar(
                select(AccountAuditEvent)
                .where(AccountAuditEvent.event_type == "ABM_ACCOUNT_LOGIN")
                .order_by(AccountAuditEvent.created_at.desc())
            )
            assert row is not None
            return dict(row.event_metadata)

    metadata = asyncio.run(latest_login())
    assert metadata["ipAddress"]
    assert metadata["method"] == "password"
    assert metadata["sessionId"]


def test_cleanup_account_sessions_respects_retention(
    admin_client: TestClient, admin_database: Database
) -> None:
    _login(admin_client)
    moment = utcnow()

    async def seed() -> tuple[str, str]:
        async with admin_database.sessions() as session:
            user = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
            assert user is not None
            stale = AccountSession(
                user_id=user.id,
                token_hash="stale-token",
                csrf_hash="stale-csrf",
                created_at=moment - timedelta(days=200),
                expires_at=moment - timedelta(days=190),
                last_seen_at=moment - timedelta(days=200),
                ip_address="198.51.100.7",
            )
            fresh = AccountSession(
                user_id=user.id,
                token_hash="fresh-token",
                csrf_hash="fresh-csrf",
                created_at=moment - timedelta(days=10),
                expires_at=moment + timedelta(days=10),
                last_seen_at=moment,
                ip_address="198.51.100.8",
            )
            session.add_all([stale, fresh])
            await session.commit()
            return stale.id, fresh.id

    stale_id, fresh_id = asyncio.run(seed())
    removed = asyncio.run(cleanup_account_sessions(admin_database, retention_days=90, now=moment))
    assert removed >= 1

    async def remaining() -> set[str]:
        async with admin_database.sessions() as session:
            rows = await session.scalars(select(AccountSession.id))
            return set(rows.all())

    ids = asyncio.run(remaining())
    assert stale_id not in ids
    assert fresh_id in ids
