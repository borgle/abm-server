from __future__ import annotations

import pytest

from abm_server.storage import LocalStorage, StorageError, media_key


@pytest.fixture
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "media")


async def test_put_get_delete_roundtrip(storage: LocalStorage) -> None:
    key = media_key("user-1", "a" * 64, "png")
    payload = b"\x89PNG\r\n\x1a\npublic"
    stored = await storage.put(key, payload, content_type="image/png")
    assert stored.size == len(payload)
    assert await storage.get(key) == payload
    await storage.delete(key)
    assert await storage.exists(key) is False


async def test_rejects_traversal_keys(storage: LocalStorage) -> None:
    for key in ("../escape.png", "/absolute.png", "media/./file.png"):
        with pytest.raises(StorageError):
            await storage.put(key, b"x")
