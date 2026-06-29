from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from pathlib import Path

from cfin_agents.paths import attachment_backend_name, runtime_data_dir

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
    "text/plain",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}


def sanitize_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^\w.\-() ]+", "_", base).strip("._ ")
    return cleaned[:180] or "upload"


def _object_key(ticket_id: str, attachment_id: str, filename: str) -> str:
    safe_name = sanitize_filename(filename)
    prefix = os.getenv("S3_PREFIX", "attachments/").strip() or "attachments/"
    if prefix and not prefix.endswith("/"):
        prefix = f"{prefix}/"
    return f"{prefix}{ticket_id}/{attachment_id}_{safe_name}"


class AttachmentStorage(ABC):
    @abstractmethod
    def put(
        self,
        ticket_id: str,
        attachment_id: str,
        filename: str,
        content: bytes,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def get(
        self,
        ticket_id: str,
        attachment_id: str,
        filename: str,
    ) -> bytes | None:
        raise NotImplementedError

    @abstractmethod
    def clear_all(self) -> None:
        raise NotImplementedError


class LocalAttachmentStorage(AttachmentStorage):
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (runtime_data_dir() / "attachments")

    def _path(self, ticket_id: str, attachment_id: str, filename: str) -> Path:
        safe_name = sanitize_filename(filename)
        return self.root / ticket_id / f"{attachment_id}_{safe_name}"

    def put(
        self,
        ticket_id: str,
        attachment_id: str,
        filename: str,
        content: bytes,
    ) -> str:
        path = self._path(ticket_id, attachment_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    def get(
        self,
        ticket_id: str,
        attachment_id: str,
        filename: str,
    ) -> bytes | None:
        path = self._path(ticket_id, attachment_id, filename)
        return path.read_bytes() if path.is_file() else None

    def clear_all(self) -> None:
        if not self.root.exists():
            return
        for path in self.root.iterdir():
            if path.is_dir():
                for file_path in path.iterdir():
                    file_path.unlink(missing_ok=True)
                path.rmdir()
            else:
                path.unlink(missing_ok=True)


class S3AttachmentStorage(AttachmentStorage):
    def __init__(self) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "STORAGE_BACKEND=s3 requires boto3. Install with: uv add boto3"
            ) from exc

        bucket = os.getenv("S3_BUCKET", "").strip()
        if not bucket:
            raise RuntimeError("S3_BUCKET is required when STORAGE_BACKEND=s3.")

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
            aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID") or None,
            aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY") or None,
            region_name=os.getenv("S3_REGION", "auto") or "auto",
        )

    def put(
        self,
        ticket_id: str,
        attachment_id: str,
        filename: str,
        content: bytes,
    ) -> str:
        key = _object_key(ticket_id, attachment_id, filename)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content)
        return key

    def get(
        self,
        ticket_id: str,
        attachment_id: str,
        filename: str,
    ) -> bytes | None:
        key = _object_key(ticket_id, attachment_id, filename)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        return response["Body"].read()

    def clear_all(self) -> None:
        prefix = os.getenv("S3_PREFIX", "attachments/").strip() or "attachments/"
        if prefix and not prefix.endswith("/"):
            prefix = f"{prefix}/"
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            contents = page.get("Contents") or []
            if not contents:
                continue
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": item["Key"]} for item in contents]},
            )


_storage: AttachmentStorage | None = None


def get_attachment_storage() -> AttachmentStorage:
    global _storage
    if _storage is None:
        backend = attachment_backend_name()
        if backend == "s3":
            _storage = S3AttachmentStorage()
        elif backend == "local":
            _storage = LocalAttachmentStorage()
        else:
            raise RuntimeError(f"Unsupported STORAGE_BACKEND '{backend}'. Use 'local' or 's3'.")
    return _storage


def save_attachment_bytes(
    ticket_id: str,
    attachment_id: str,
    filename: str,
    content: bytes,
) -> str:
    return get_attachment_storage().put(ticket_id, attachment_id, filename, content)


def read_attachment_bytes(
    ticket_id: str,
    attachment_id: str,
    filename: str,
) -> bytes | None:
    return get_attachment_storage().get(ticket_id, attachment_id, filename)


def clear_attachments() -> None:
    get_attachment_storage().clear_all()


# Backward-compatible alias used in tests / legacy imports
ATTACHMENTS_DIR = runtime_data_dir() / "attachments"


def resolve_attachment_path(ticket_id: str, attachment_id: str, filename: str) -> Path | None:
    """Local path lookup — only meaningful for local backend."""
    path = LocalAttachmentStorage()._path(ticket_id, attachment_id, filename)
    return path if path.is_file() else None
