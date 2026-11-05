"""Storage factory and public exports."""

from __future__ import annotations

from ..config import Settings
from .base import (
    ObjectStorage,
    StorageError,
    StoredObject,
    digest,
    export_key,
    media_key,
)
from .local import LocalStorage
from .s3 import S3Storage

__all__ = [
    "LocalStorage",
    "ObjectStorage",
    "S3Storage",
    "StorageError",
    "StoredObject",
    "build_storage",
    "digest",
    "export_key",
    "media_key",
]


def build_storage(settings: Settings) -> ObjectStorage:
    backend = (settings.storage_backend or "local").strip().lower()
    if backend == "local":
        return LocalStorage(settings.media_root)
    if backend == "s3":
        return S3Storage(
            endpoint_url=settings.s3_endpoint_url,
            bucket=settings.s3_bucket,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            region=settings.s3_region,
            prefix=settings.s3_prefix,
            addressing_style=settings.s3_addressing_style,
            use_ssl=settings.s3_use_ssl,
            auto_create_bucket=settings.s3_auto_create_bucket,
        )
    raise StorageError(f"Unsupported storage backend: {settings.storage_backend!r}")
