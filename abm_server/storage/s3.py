"""S3-compatible object storage (MinIO, AWS S3, Cloudflare R2, ...)."""

from __future__ import annotations

import asyncio
from typing import Any

from .base import ObjectStorage, StorageError, StoredObject, digest


class S3Storage(ObjectStorage):
    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "us-east-1",
        prefix: str = "abm",
        addressing_style: str = "path",
        use_ssl: bool = False,
        auto_create_bucket: bool = True,
    ) -> None:
        if not bucket:
            raise StorageError("ABM_S3_BUCKET is required when storage backend is s3")
        if not access_key_id or not secret_access_key:
            raise StorageError(
                "ABM_S3_ACCESS_KEY_ID and ABM_S3_SECRET_ACCESS_KEY are required for s3 storage"
            )
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.region = region
        self._endpoint_url = endpoint_url or None
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._addressing_style = addressing_style
        self._use_ssl = use_ssl
        self._auto_create_bucket = auto_create_bucket
        self._client: Any = None
        self._bucket_ready = False

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise StorageError("S3 storage requires boto3: pip install 'abm-server[s3]'") from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            region_name=self.region,
            use_ssl=self._use_ssl,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": self._addressing_style},
            ),
        )
        return self._client

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    async def _ensure_bucket(self) -> None:
        if self._bucket_ready or not self._auto_create_bucket:
            return

        def run() -> None:
            client = self._get_client()
            try:
                client.head_bucket(Bucket=self.bucket)
            except Exception as exc:  # noqa: BLE001 - botocore error types vary
                code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
                if code not in {"404", "NoSuchBucket", "NotFound"}:
                    raise StorageError(f"Cannot access bucket {self.bucket!r}: {exc}") from exc
                params: dict[str, Any] = {"Bucket": self.bucket}
                if self.region and self.region != "us-east-1":
                    params["CreateBucketConfiguration"] = {
                        "LocationConstraint": self.region,
                    }
                client.create_bucket(**params)

        await asyncio.to_thread(run)
        self._bucket_ready = True

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        await self._ensure_bucket()
        full_key = self._full_key(key)

        def run() -> None:
            self._get_client().put_object(
                Bucket=self.bucket,
                Key=full_key,
                Body=data,
                ContentType=content_type,
            )

        try:
            await asyncio.to_thread(run)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Failed to upload {key!r}: {exc}") from exc
        return StoredObject(key=key, size=len(data), sha256=digest(data))

    async def get(self, key: str) -> bytes:
        full_key = self._full_key(key)

        def run() -> bytes:
            client = self._get_client()
            try:
                response = client.get_object(Bucket=self.bucket, Key=full_key)
            except Exception as exc:  # noqa: BLE001
                code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
                if code in {"NoSuchKey", "404", "NotFound"}:
                    raise StorageError(f"Object not found: {key}") from exc
                raise
            return response["Body"].read()

        try:
            return await asyncio.to_thread(run)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Failed to read {key!r}: {exc}") from exc

    async def delete(self, key: str) -> None:
        full_key = self._full_key(key)

        def run() -> None:
            self._get_client().delete_object(Bucket=self.bucket, Key=full_key)

        try:
            await asyncio.to_thread(run)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Failed to delete {key!r}: {exc}") from exc

    async def exists(self, key: str) -> bool:
        full_key = self._full_key(key)

        def run() -> bool:
            client = self._get_client()
            try:
                client.head_object(Bucket=self.bucket, Key=full_key)
                return True
            except Exception as exc:  # noqa: BLE001
                code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
                if code in {"NoSuchKey", "404", "NotFound"}:
                    return False
                raise

        return await asyncio.to_thread(run)
