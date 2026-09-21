"""Profile the source datasets required for challenge Sections 0-2.

The report intentionally excludes row values because service-request records may
contain resident or address information. CSV files are streamed from S3 and the
large mixed-resolution GeoJSON is inspected with S3 Select.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import boto3

from check_source_access import BUCKET, REGION, load_dummy_credentials

SERVICE_REQUEST_OBJECTS = ("sr.csv.gz", "sr_hex.csv.gz")
LEVEL_8_OBJECT = "city-hex-polygons-8.geojson"
MIXED_RESOLUTION_OBJECT = "city-hex-polygons-8-10.geojson"
NULL_MARKERS = {"", "null", "none", "na", "n/a", "nan"}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for the JSON profile.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print the report; intended for runs that use --output.",
    )
    return parser.parse_args()


def is_null(value: str | None) -> bool:
    """Return whether a CSV value represents a missing value."""
    return value is None or value.strip().lower() in NULL_MARKERS


def scalar_kind(value: str) -> str:
    """Infer a conservative scalar kind without retaining the value."""
    stripped = value.strip()
    try:
        int(stripped)
        return "integer"
    except ValueError:
        pass
    try:
        number = float(stripped)
        return "number" if math.isfinite(number) else "non_finite_number"
    except ValueError:
        return "string"


def inferred_kind(type_counts: Counter[str]) -> str:
    """Collapse observed scalar kinds to one practical storage type."""
    observed = set(type_counts)
    if not observed:
        return "unknown_all_null"
    if observed <= {"integer"}:
        return "integer"
    if observed <= {"integer", "number"}:
        return "number"
    return "string"


def profile_csv(client: Any, object_key: str) -> dict[str, Any]:
    """Stream a gzip-compressed CSV and calculate privacy-safe statistics."""
    response = client.get_object(Bucket=BUCKET, Key=object_key)
    compressed = gzip.GzipFile(fileobj=response["Body"])
    text_stream = io.TextIOWrapper(compressed, encoding="utf-8-sig", newline="")
    reader = csv.DictReader(text_stream)
    if reader.fieldnames is None:
        raise ValueError(f"{object_key} has no CSV header")

    columns = list(reader.fieldnames)
    columns_by_lower_name = {column.lower(): column for column in columns}
    latitude_column = columns_by_lower_name.get("latitude")
    longitude_column = columns_by_lower_name.get("longitude")
    null_counts = Counter({column: 0 for column in columns})
    type_counts = {column: Counter() for column in columns}
    max_lengths = Counter({column: 0 for column in columns})
    coordinate_stats = {
        "valid_pairs": 0,
        "invalid_or_missing_pairs": 0,
        "latitude_min": None,
        "latitude_max": None,
        "longitude_min": None,
        "longitude_max": None,
    }
    h3_counts = Counter()
    unique_h3_indexes: set[str] = set()
    row_count = 0

    for row in reader:
        row_count += 1
        for column in columns:
            value = row.get(column)
            if is_null(value):
                null_counts[column] += 1
                continue
            assert value is not None
            type_counts[column][scalar_kind(value)] += 1
            max_lengths[column] = max(max_lengths[column], len(value))

        latitude = row.get(latitude_column) if latitude_column else None
        longitude = row.get(longitude_column) if longitude_column else None
        try:
            if is_null(latitude) or is_null(longitude):
                raise ValueError
            latitude_number = float(latitude)  # type: ignore[arg-type]
            longitude_number = float(longitude)  # type: ignore[arg-type]
            if not math.isfinite(latitude_number) or not math.isfinite(longitude_number):
                raise ValueError
        except (TypeError, ValueError):
            coordinate_stats["invalid_or_missing_pairs"] += 1
        else:
            coordinate_stats["valid_pairs"] += 1
            for name, number in (
                ("latitude", latitude_number),
                ("longitude", longitude_number),
            ):
                minimum_key = f"{name}_min"
                maximum_key = f"{name}_max"
                current_minimum = coordinate_stats[minimum_key]
                current_maximum = coordinate_stats[maximum_key]
                coordinate_stats[minimum_key] = (
                    number if current_minimum is None else min(current_minimum, number)
                )
                coordinate_stats[maximum_key] = (
                    number if current_maximum is None else max(current_maximum, number)
                )

        if "h3_level8_index" in row:
            index = row.get("h3_level8_index")
            if is_null(index):
                h3_counts["null"] += 1
            elif index == "0":
                h3_counts["zero"] += 1
            else:
                h3_counts["nonzero"] += 1
                assert index is not None
                unique_h3_indexes.add(index)

    column_profiles = []
    for column in columns:
        null_count = null_counts[column]
        column_profiles.append(
            {
                "name": column,
                "inferred_storage_type": inferred_kind(type_counts[column]),
                "null_count": null_count,
                "null_percentage": round(100 * null_count / row_count, 4)
                if row_count
                else None,
                "maximum_text_length": max_lengths[column],
            }
        )

    report: dict[str, Any] = {
        "object_key": object_key,
        "compressed_size_bytes": response["ContentLength"],
        "row_count": row_count,
        "column_count": len(columns),
        "columns": columns,
        "column_profiles": column_profiles,
        "coordinate_columns": {
            "latitude": latitude_column,
            "longitude": longitude_column,
        },
        "coordinates": coordinate_stats,
        "raw_row_values_included": False,
    }
    if "h3_level8_index" in columns:
        report["h3_level8_index"] = {
            **dict(h3_counts),
            "unique_nonzero_count": len(unique_h3_indexes),
        }
    return report


def json_type(value: Any) -> str:
    """Return a JSON-oriented type label."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def positions(coordinates: Any) -> Iterable[tuple[float, float]]:
    """Yield longitude/latitude pairs from arbitrarily nested GeoJSON coordinates."""
    if (
        isinstance(coordinates, list)
        and len(coordinates) >= 2
        and isinstance(coordinates[0], (int, float))
        and isinstance(coordinates[1], (int, float))
    ):
        yield float(coordinates[0]), float(coordinates[1])
        return
    if isinstance(coordinates, list):
        for item in coordinates:
            yield from positions(item)


def profile_feature_collection(payload: dict[str, Any], object_key: str) -> dict[str, Any]:
    """Profile a GeoJSON FeatureCollection without retaining feature values."""
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError(f"{object_key} does not contain a features array")

    geometry_types = Counter()
    property_types: dict[str, Counter[str]] = {}
    property_nulls = Counter()
    property_unique_values: dict[str, set[Any]] = {}
    longitude_min = longitude_max = latitude_min = latitude_max = None

    for feature in features:
        geometry = feature.get("geometry") or {}
        geometry_types[str(geometry.get("type"))] += 1
        for longitude, latitude in positions(geometry.get("coordinates")):
            longitude_min = longitude if longitude_min is None else min(longitude_min, longitude)
            longitude_max = longitude if longitude_max is None else max(longitude_max, longitude)
            latitude_min = latitude if latitude_min is None else min(latitude_min, latitude)
            latitude_max = latitude if latitude_max is None else max(latitude_max, latitude)

        properties = feature.get("properties") or {}
        for name, value in properties.items():
            property_types.setdefault(name, Counter())[json_type(value)] += 1
            if value is None:
                property_nulls[name] += 1
            elif isinstance(value, (str, int, float, bool)):
                property_unique_values.setdefault(name, set()).add(value)

    return {
        "object_key": object_key,
        "top_level_type": payload.get("type"),
        "feature_count": len(features),
        "geometry_type_counts": dict(geometry_types),
        "property_profiles": [
            {
                "name": name,
                "observed_json_types": dict(type_counts),
                "null_count": property_nulls[name],
                "unique_non_null_count": len(property_unique_values.get(name, set())),
            }
            for name, type_counts in sorted(property_types.items())
        ],
        "bounding_box": [longitude_min, latitude_min, longitude_max, latitude_max],
        "feature_values_included": False,
    }


def read_s3_select_json(client: Any, expression: str) -> list[dict[str, Any]]:
    """Execute S3 Select and parse its newline-delimited JSON response."""
    response = client.select_object_content(
        Bucket=BUCKET,
        Key=MIXED_RESOLUTION_OBJECT,
        ExpressionType="SQL",
        Expression=expression,
        InputSerialization={"JSON": {"Type": "DOCUMENT"}},
        OutputSerialization={"JSON": {"RecordDelimiter": "\n"}},
    )
    buffer = b""
    records: list[dict[str, Any]] = []
    for event in response["Payload"]:
        if "Records" not in event:
            continue
        buffer += event["Records"]["Payload"]
        lines = buffer.split(b"\n")
        buffer = lines.pop()
        records.extend(json.loads(line) for line in lines if line)
    if buffer.strip():
        records.append(json.loads(buffer))
    return records


def profile_mixed_geojson(client: Any) -> dict[str, Any]:
    """Inspect the large GeoJSON through S3 Select instead of downloading it."""
    sample = read_s3_select_json(
        client, "SELECT * FROM S3Object[*].features[*] s LIMIT 1"
    )
    if not sample:
        raise ValueError("Mixed-resolution GeoJSON did not return a sample feature")
    sample_feature = sample[0]
    properties = sample_feature.get("properties") or {}
    geometry = sample_feature.get("geometry") or {}

    count_record = read_s3_select_json(
        client, "SELECT COUNT(*) AS feature_count FROM S3Object[*].features[*] s"
    )[0]

    resolution_field = next(
        (
            name
            for name in properties
            if name.lower() in {"resolution", "res", "h3_resolution"}
        ),
        None,
    )
    resolution_counts: Counter[str] = Counter()
    if resolution_field is not None:
        expression = (
            f'SELECT s.properties."{resolution_field}" AS resolution '
            "FROM S3Object[*].features[*] s"
        )
        for record in read_s3_select_json(client, expression):
            resolution_counts[str(record.get("resolution"))] += 1

    head = client.head_object(Bucket=BUCKET, Key=MIXED_RESOLUTION_OBJECT)
    return {
        "object_key": MIXED_RESOLUTION_OBJECT,
        "size_bytes": head["ContentLength"],
        "inspection_method": "S3 Select",
        "feature_count": count_record.get("feature_count"),
        "feature_keys": sorted(sample_feature),
        "property_profiles": [
            {"name": name, "sample_json_type": json_type(value)}
            for name, value in sorted(properties.items())
        ],
        "sample_geometry_type": geometry.get("type"),
        "resolution_field": resolution_field,
        "resolution_counts": dict(resolution_counts),
        "feature_values_included": False,
    }


def build_report(client: Any) -> dict[str, Any]:
    """Build a complete source-data profile."""
    csv_reports = [profile_csv(client, key) for key in SERVICE_REQUEST_OBJECTS]
    level_8_response = client.get_object(Bucket=BUCKET, Key=LEVEL_8_OBJECT)
    level_8_payload = json.load(io.TextIOWrapper(level_8_response["Body"], encoding="utf-8"))
    level_8_report = profile_feature_collection(level_8_payload, LEVEL_8_OBJECT)
    level_8_report["size_bytes"] = level_8_response["ContentLength"]

    base_columns = set(csv_reports[0]["columns"])
    hex_columns = set(csv_reports[1]["columns"])
    return {
        "purpose": "Privacy-safe source profile for challenge Sections 0-2",
        "bucket": BUCKET,
        "region": REGION,
        "service_request_files": csv_reports,
        "service_request_comparison": {
            "row_counts_match": csv_reports[0]["row_count"]
            == csv_reports[1]["row_count"],
            "columns_only_in_sr": sorted(base_columns - hex_columns),
            "columns_only_in_sr_hex": sorted(hex_columns - base_columns),
        },
        "level_8_geojson": level_8_report,
        "mixed_resolution_geojson": profile_mixed_geojson(client),
    }


def main() -> None:
    """Connect to S3, build the profile, and optionally save it."""
    args = parse_args()
    access_key, secret_key = load_dummy_credentials()
    client = boto3.client(
        "s3",
        region_name=REGION,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    report = build_report(client)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if not args.quiet:
        print(rendered)


if __name__ == "__main__":
    main()
