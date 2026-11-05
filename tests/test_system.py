from fastapi.testclient import TestClient


def test_health_check(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "abm-browser-mcp",
        "version": "0.1.0",
    }
    assert response.headers["x-request-id"].startswith("req_")


def test_request_id_is_preserved(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "req_test"})
    assert response.headers["x-request-id"] == "req_test"


def test_readiness_check(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_settings_use_abm_prefix(monkeypatch) -> None:
    from abm_server.config import Settings

    monkeypatch.setenv("ABM_PORT", "19000")
    monkeypatch.setenv("ABM_MAX_ACTIVE_KEYS_FREE", "3")
    config = Settings(_env_file=None)
    assert config.port == 19000
    assert config.max_active_keys_free == 3
