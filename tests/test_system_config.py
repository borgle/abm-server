from fastapi.testclient import TestClient


def _login(client: TestClient) -> dict[str, str]:
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "admin-password-123"},
        ).status_code
        == 200
    )
    token = client.cookies.get("abm_csrf")
    assert token
    return {"X-CSRF-Token": token}


def test_system_config_groups_and_patch(admin_client: TestClient) -> None:
    headers = _login(admin_client)
    response = admin_client.get("/api/v1/admin/system/config")
    assert response.status_code == 200
    payload = response.json()
    groups = {group["id"]: group for group in payload["groups"]}
    assert "accounts" in groups
    assert "browser" in groups
    keys = {item["key"] for group in groups.values() for item in group["items"]}
    assert "quota_tool_calls_free" in keys
    assert "extension_reserved_priority_slots" in keys

    patched = admin_client.patch(
        "/api/v1/admin/system/config",
        json={
            "values": {
                "quota_tool_calls_free": 1234,
                "email_mode": "smtp",
                "social_login_enabled": False,
            }
        },
        headers=headers,
    )
    assert patched.status_code == 200
    settings = admin_client.app.state.settings
    assert settings.quota_tool_calls_free == 1234
    assert settings.email_mode == "smtp"
    assert settings.social_login_enabled is False

    refreshed = admin_client.get("/api/v1/admin/system/config").json()
    items = {item["key"]: item for group in refreshed["groups"] for item in group["items"]}
    assert items["quota_tool_calls_free"]["source"] == "database"
    assert items["quota_tool_calls_free"]["value"] == 1234

    invalid = admin_client.patch(
        "/api/v1/admin/system/config",
        json={"values": {"not_a_setting": 1}},
        headers=headers,
    )
    assert invalid.status_code == 422
    invalid_range = admin_client.patch(
        "/api/v1/admin/system/config",
        json={"values": {"password_min_length": 2}},
        headers=headers,
    )
    assert invalid_range.status_code == 422


def test_system_config_export_import_and_replace(admin_client: TestClient) -> None:
    headers = _login(admin_client)
    admin_client.patch(
        "/api/v1/admin/system/config",
        json={
            "values": {
                "quota_tool_calls_free": 1500,
                "quota_tool_calls_pro": 5000,
            }
        },
        headers=headers,
    )
    export = admin_client.get("/api/v1/admin/system/config/export")
    assert export.status_code == 200
    assert "attachment" in export.headers["content-disposition"]
    values = export.json()["values"]
    assert values["quota_tool_calls_free"] == 1500

    replaced = admin_client.post(
        "/api/v1/admin/system/config/import",
        json={"values": {"quota_tool_calls_free": 777}, "mode": "replace"},
        headers=headers,
    )
    assert replaced.status_code == 200
    settings = admin_client.app.state.settings
    assert settings.quota_tool_calls_free == 777
    # Omitted overrides fall back to the startup/env value.
    assert settings.quota_tool_calls_pro == 20_000

    invalid = admin_client.post(
        "/api/v1/admin/system/config/import",
        json={"values": {"email_mode": "carrier-pigeon"}},
        headers=headers,
    )
    assert invalid.status_code == 422
