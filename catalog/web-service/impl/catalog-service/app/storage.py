# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
MOCKED S3 stand-in for the local reference implementation.

Production (§9.1) uses real S3 pre-signed PUT URLs for icons, deployment
files, and evidence uploads. Here, "pre-signed URL" issuance just returns a
local `/dev/storage/{key}` path served by this same FastAPI app, and the
ISV/browser client PUTs bytes straight to it. Swapping to real S3 only
requires replacing `presign_upload`/`local storage` router with boto3 calls
— callers only ever see a URL.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

STORAGE_DIR = os.environ.get(
    "CATALOG_STORAGE_DIR",
    os.path.join(os.path.dirname(__file__), "..", "_storage"),
)
os.makedirs(STORAGE_DIR, exist_ok=True)


def presign_upload(prefix: str, base_url: str) -> dict:
    key = f"{prefix}/{uuid.uuid4()}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    return {
        "upload_url": f"{base_url}/dev/storage/{key}",
        "method": "PUT",
        "expires_at": expires_at,
        "final_url": f"{base_url}/dev/storage/{key}",
        "key": key,
    }


def key_from_url(url: str) -> str | None:
    marker = "/dev/storage/"
    if marker in url:
        return url.split(marker, 1)[1]
    return None


def write_bytes(key: str, data: bytes) -> None:
    path = os.path.join(STORAGE_DIR, key.replace("/", "__"))
    with open(path, "wb") as f:
        f.write(data)


def read_bytes(key: str) -> bytes:
    path = os.path.join(STORAGE_DIR, key.replace("/", "__"))
    with open(path, "rb") as f:
        return f.read()


def exists(key: str) -> bool:
    path = os.path.join(STORAGE_DIR, key.replace("/", "__"))
    return os.path.exists(path)
