from __future__ import annotations

import pytest

from abm_server.storage import (
    LocalStorage,
    StorageError,
    digest,
    export_key,
    media_key,
)


@pytest.fixture
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "media")


async def test_put_get_roundtrip(storage: LocalStorage) -> None:
    key = media_key("user-1", "a" * 64, "png")
    payload = b"\x89PNG\r\n\x1a\nfake"

    stored = await storage.put(key, payload, content_type="image/png")

    assert stored.key == key
    assert stored.size == len(payload)
    assert stored.sha256 == digest(payload)
    assert await storage.get(key) == payload
    assert await storage.exists(key) is True


async def test_put_overwrites_and_is_idempotent(storage: LocalStorage) -> None:
    key = media_key("user-1", "b" * 64, "png")
    await storage.put(key, b"one")
    await storage.put(key, b"two")
    assert await storage.get(key) == b"two"


async def test_delete_missing_is_silent(storage: LocalStorage) -> None:
    await storage.delete("media/missing/file.png")
    assert await storage.exists("media/missing/file.png") is False


async def test_get_missing_raises(storage: LocalStorage) -> None:
    with pytest.raises(StorageError):
        await storage.get("media/missing/file.png")


@pytest.mark.parametrize(
    "key",
    [
        "../escape.png",
        "media/../../escape.png",
        "/absolute/path.png",
        "media/./file.png",
    ],
)
async def test_rejects_unsafe_keys(storage: LocalStorage, key: str) -> None:
    with pytest.raises(StorageError):
        await storage.put(key, b"data")


def test_media_key_is_per_user_and_content_addressed() -> None:
    sha = "c" * 64
    assert media_key("user-1", sha, "png") == f"media/user-1/cc/{sha}.png"
    assert media_key("user-1", sha, ".jpg") == f"media/user-1/cc/{sha}.jpg"
    assert media_key("user-1", sha) == f"media/user-1/cc/{sha}"


def test_export_key_layout() -> None:
    assert export_key("user-1", "export-1", "export.html") == (
        "exports/user-1/export-1/export.html"
    )
