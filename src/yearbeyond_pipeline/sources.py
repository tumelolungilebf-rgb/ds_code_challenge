"""Shared access to the public challenge sources in Amazon S3."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.request import urlopen

import boto3
from botocore.config import Config

BUCKET = "cct-ds-code-challenge-input-data"
REGION = "af-south-1"
CREDENTIALS_URL = (
    f"https://{BUCKET}.s3.{REGION}.amazonaws.com/"
    "ds_code_challenge_creds.json"
)
MIXED_RESOLUTION_OBJECT = "city-hex-polygons-8-10.geojson"
LEVEL_8_REFERENCE_OBJECT = "city-hex-polygons-8.geojson"
SERVICE_REQUEST_OBJECT = "sr.csv.gz"
SERVICE_REQUEST_REFERENCE_OBJECT = "sr_hex.csv.gz"


class SourceAccessError(RuntimeError):
    """Raised when source credentials or data have an unexpected structure."""


def load_dummy_credentials() -> tuple[str, str]:
    """Load the supplied read credentials without storing or displaying them."""
    with urlopen(CREDENTIALS_URL, timeout=30) as response:
        payload = json.load(response)

    try:
        access_key = payload["s3"]["access_key"]
        secret_key = payload["s3"]["secret_key"]
    except (KeyError, TypeError) as error:
        raise SourceAccessError("Unexpected credential-file structure") from error

    if not all(isinstance(value, str) and value for value in (access_key, secret_key)):
        raise SourceAccessError("Credential values must be nonempty strings")
    return access_key, secret_key


def create_s3_client() -> Any:
    """Create a bounded-retry S3 client for the challenge region."""
    access_key, secret_key = load_dummy_credentials()
    return boto3.client(
        "s3",
        region_name=REGION,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            connect_timeout=10,
            read_timeout=120,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def get_object_metadata(client: Any, object_key: str) -> dict[str, Any]:
    """Return stable, JSON-serializable object metadata used for run auditing."""
    response = client.head_object(Bucket=BUCKET, Key=object_key)
    last_modified = response.get("LastModified")
    if isinstance(last_modified, datetime):
        last_modified = last_modified.isoformat()
    return {
        "object_key": object_key,
        "size_bytes": response.get("ContentLength"),
        "etag": response.get("ETag"),
        "last_modified": last_modified,
        "version_id": response.get("VersionId"),
    }


def read_json_object(client: Any, object_key: str) -> dict[str, Any]:
    """Read a small JSON object and require a JSON object at the root."""
    response = client.get_object(Bucket=BUCKET, Key=object_key)
    body = response["Body"]
    try:
        payload = json.load(body)
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    if not isinstance(payload, dict):
        raise SourceAccessError(f"{object_key} does not contain a JSON object")
    return payload
