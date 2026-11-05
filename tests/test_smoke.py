from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin-password-123"},
    )
    assert response.status_code == 200
    token = client.cookies.get("abm_csrf")
    assert token
    return token


def test_single_edition_blocks_registration(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "second@example.com",
            "password": "another-password-123",
            "display_name": "Second",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ABM_REGISTRATION_DISABLED"
    assert client.get("/register").status_code == 404


def test_single_edition_hides_multi_user_admin(client: TestClient) -> None:
    _login(client)
    assert client.get("/api/v1/admin/users").status_code == 404
    assert client.get("/api/v1/admin/audit").status_code == 404
    assert client.get("/admin/users").status_code == 404
    assert client.get("/admin/plans").status_code == 200


def test_creation_workspace_pages_load(client: TestClient) -> None:
    _login(client)
    for path in ("/creation/overview", "/creation/library", "/creation/studio", "/creation/publish"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'data-app="creation"' in response.text


def test_local_model_config_roundtrip(client: TestClient) -> None:
    token = _login(client)
    headers = {"X-CSRF-Token": token}
    provider = client.post(
        "/api/v1/admin/creation/providers",
        json={
            "name": "Local provider",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-1234",
        },
        headers=headers,
    )
    assert provider.status_code == 201
    provider_id = provider.json()["provider"]["id"]

    updated = client.put(
        "/api/v1/admin/local-model",
        json={
            "provider_id": provider_id,
            "model": "local-chat",
            "image_provider_id": provider_id,
            "image_model": "local-image",
        },
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["local"]["model"] == "local-chat"
