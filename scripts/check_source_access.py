"""Verify read access to the source objects required for Sections 0-2."""

from __future__ import annotations

import json
from urllib.request import urlopen

import boto3
from botocore.exceptions import ClientError

BUCKET = "cct-ds-code-challenge-input-data"
REGION = "af-south-1"
CREDENTIALS_URL = (
    f"https://{BUCKET}.s3.{REGION}.amazonaws.com/"
    "ds_code_challenge_creds.json"
)
REQUIRED_OBJECTS = (
    "sr.csv.gz",
    "sr_hex.csv.gz",
    "city-hex-polygons-8.geojson",
    "city-hex-polygons-8-10.geojson",
)
S3_SELECT_OBJECT = "city-hex-polygons-8-10.geojson"
S3_SELECT_PROBE = "SELECT * FROM S3Object[*].features[*] s LIMIT 1"


def load_dummy_credentials() -> tuple[str, str]:
    """Load the challenge credentials without writing or displaying them."""
    with urlopen(CREDENTIALS_URL, timeout=30) as response:
        payload = json.load(response)

    try:
        access_key = payload["s3"]["access_key"]
        secret_key = payload["s3"]["secret_key"]
    except (KeyError, TypeError) as error:
        raise ValueError("Unexpected credential-file structure") from error

    if not isinstance(access_key, str) or not isinstance(secret_key, str):
        raise ValueError("Credential values must be strings")

    return access_key, secret_key


def probe_s3_select(client: object) -> dict[str, object]:
    """Check S3 Select availability without printing the returned feature."""
    try:
        response = client.select_object_content(
            Bucket=BUCKET,
            Key=S3_SELECT_OBJECT,
            ExpressionType="SQL",
            Expression=S3_SELECT_PROBE,
            InputSerialization={"JSON": {"Type": "DOCUMENT"}},
            OutputSerialization={"JSON": {"RecordDelimiter": "\n"}},
        )
        returned_bytes = 0
        statistics: dict[str, int] = {}
        for event in response["Payload"]:
            if "Records" in event:
                returned_bytes += len(event["Records"]["Payload"])
            elif "Stats" in event:
                statistics = event["Stats"]["Details"]
    except ClientError as error:
        error_details = error.response["Error"]
        return {
            "available": False,
            "error_code": error_details.get("Code", "Unknown"),
            "error_message": error_details.get("Message", "Unknown error"),
        }

    return {
        "available": True,
        "query": S3_SELECT_PROBE,
        "returned_bytes": returned_bytes,
        "statistics": statistics,
    }


def main() -> None:
    """Check that every required object is readable through the AWS SDK."""
    access_key, secret_key = load_dummy_credentials()
    client = boto3.client(
        "s3",
        region_name=REGION,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    object_results = []
    for object_key in REQUIRED_OBJECTS:
        response = client.head_object(Bucket=BUCKET, Key=object_key)
        object_results.append(
            {
                "object_key": object_key,
                "status_code": response["ResponseMetadata"]["HTTPStatusCode"],
                "size_bytes": response["ContentLength"],
            }
        )

    report = {
        "bucket": BUCKET,
        "region": client.meta.region_name,
        "credentials_loaded": True,
        "credentials_displayed": False,
        "objects": object_results,
        "s3_select_probe": probe_s3_select(client),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
