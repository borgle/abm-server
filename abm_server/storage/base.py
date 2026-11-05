"""Object storage abstraction for creation media and exports.

Media bytes never live in the database: rows only keep a storage key and the
checksum. The default backend writes to a local directory so the single-user
build stays dependency-free; hosted deployments point at S3/MinIO.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class StorageError(Exception):
    """Raised when an object cannot be written or read."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    sha256: str


@runtime_checkable
class ObjectStorage(Protocol):
    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> StoredObject: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def media_key(user_id: str, sha256: str, suffix: str = "") -> str:
    """Build a per-user, content-addressed key.

    Keeping the user prefix means deleting an account can drop one prefix, and
    quota accounting never has to reason about cross-tenant dedupe.
    """

    suffix = suffix if suffix.startswith(".") else f".{suffix}" if suffix else ""
    return f"media/{user_id}/{sha256[:2]}/{sha256}{suffix}"


def export_key(user_id: str, export_id: str, filename: str) -> str:
    return f"exports/{user_id}/{export_id}/{filename}"
