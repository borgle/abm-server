"""Local filesystem object storage (default for the single-user build)."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path, PurePosixPath

from .base import ObjectStorage, StorageError, StoredObject, digest


class LocalStorage(ObjectStorage):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        segments = key.split("/")
        if not key or key.startswith("/") or "\\" in key:
            raise StorageError(f"Invalid storage key: {key!r}")
        if any(segment in {"..", "."} or not segment for segment in segments):
            raise StorageError(f"Invalid storage key: {key!r}")
        pure = PurePosixPath(key)
        target = (self.root / Path(*pure.parts)).resolve()
        if self.root not in target.parents and target != self.root:
            raise StorageError(f"Invalid storage key: {key!r}")
        return target

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        target = self._path(key)
        await asyncio.to_thread(self._write, target, data)
        return StoredObject(key=key, size=len(data), sha256=digest(data))

    @staticmethod
    def _write(target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    async def get(self, key: str) -> bytes:
        target = self._path(key)
        try:
            return await asyncio.to_thread(target.read_bytes)
        except FileNotFoundError as exc:
            raise StorageError(f"Object not found: {key}") from exc

    async def delete(self, key: str) -> None:
        target = self._path(key)
        await asyncio.to_thread(target.unlink, True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)
