from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from abm_server.config import Settings
from abm_server.database import Database
from abm_server.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'public.db'}",
        session_cookie_secure=False,
        bootstrap_admin_email="admin@example.com",
        bootstrap_admin_password="admin-password-123",
        creation_secret_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        media_root=str(tmp_path / "media"),
        edition="single",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    database = Database(settings)
    asyncio.run(database.create_schema())
    with TestClient(create_app(settings, database)) as test_client:
        yield test_client


def login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin-password-123"},
    )
    assert response.status_code == 200
    token = client.cookies.get("abm_csrf")
    assert token
    return token
