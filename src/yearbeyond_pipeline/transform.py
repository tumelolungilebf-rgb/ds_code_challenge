"""Streaming H3 assignment and reference validation for Section 2."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
from collections import Counter
from contextlib import contextmanager
from itertools import zip_longest
from pathlib import Path
from typing import Any, Iterator, TextIO

import h3

from .sources import BUCKET


class TransformationError(RuntimeError):
    """Raised when Section 2 input or configuration is unsafe to process."""


def load_policy(path: Path) -> dict[str, Any]:
    """Load and minimally validate the standalone Section 2 policy."""
    policy = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "resolution",
        "latitude_field",
        "longitude_field",
        "row_identity_field",
        "output_index_field",
        "missing_coordinate_index",
        "original_grid_unjoined_rate",
        "unexpected_join_error_rate",
        "reference_validation",
    }
    if not isinstance(policy, dict) or not required <= policy.keys():
        raise TransformationError("Section 2 policy is missing required settings")
    if policy["resolution"] != 8 or policy["missing_coordinate_index"] != "0":
        raise TransformationError("Section 2 policy must assign resolution 8 and missing index 0")
    for name in ("original_grid_unjoined_rate", "unexpected_join_error_rate"):
        maximum = policy[name].get("maximum_fraction")
        if isinstance(maximum, bool) or not isinstance(maximum, (int, float)):
            raise TransformationError(f"{name} maximum_fraction must be numeric")
        if not 0 <= maximum <= 1:
            raise TransformationError(f"{name} maximum_fraction must be in [0, 1]")
    return policy


def load_grid(path: Path, resolution: int) -> tuple[set[str], str]:
    """Load the validated Section 1 grid and return its unique cell set and hash."""
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("type") != "FeatureCollection" or not payload.get("features"):
        raise TransformationError("Grid must be a nonempty GeoJSON FeatureCollection")
    cells: list[str] = []
    for feature in payload["features"]:
        try:
            cell = feature["properties"]["index"]
        except (KeyError, TypeError) as error:
            raise TransformationError("Every grid feature must have an index") from error
        if not h3.is_valid_cell(cell) or h3.get_resolution(cell) != resolution:
            raise TransformationError(f"Grid contains an invalid resolution-{resolution} index")
        cells.append(cell)
    if len(cells) != len(set(cells)):
        raise TransformationError("Grid contains duplicate H3 indices")
    return set(cells), hashlib.sha256(raw).hexdigest()


def classify_coordinates(latitude: str, longitude: str, resolution: int) -> tuple[str, str]:
    """Classify coordinate text and return its calculated H3 address when usable."""
    latitude_missing = not latitude.strip()
    longitude_missing = not longitude.strip()
    if latitude_missing or longitude_missing:
        category = "missing_both" if latitude_missing and longitude_missing else "missing_one"
        return category, "0"
    try:
        lat, lon = float(latitude), float(longitude)
    except ValueError:
        return "nonnumeric", "0"
    if not math.isfinite(lat) or not math.isfinite(lon):
        return "nonfinite", "0"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return "out_of_range", "0"
    return "usable", h3.latlng_to_cell(lat, lon, resolution)


@contextmanager
def open_s3_gzip_csv(client: Any, object_key: str) -> Iterator[csv.DictReader]:
    """Yield a streaming UTF-8 CSV reader for a gzip-compressed S3 object."""
    response = client.get_object(Bucket=BUCKET, Key=object_key)
    body = response["Body"]
    compressed = gzip.GzipFile(fileobj=body, mode="rb")
    text = io.TextIOWrapper(compressed, encoding="utf-8-sig", newline="")
    try:
        yield csv.DictReader(text)
    finally:
        text.close()
        close = getattr(body, "close", None)
        if callable(close):
            close()


def _validate_headers(headers: list[str] | None, policy: dict[str, Any]) -> list[str]:
    if not headers or len(headers) != len(set(headers)):
        raise TransformationError("Source CSV has missing or duplicate headers")
    required = {
        policy["latitude_field"],
        policy["longitude_field"],
        policy["row_identity_field"],
    }
    if not required <= set(headers):
        raise TransformationError("Source CSV is missing a required field")
    if policy["output_index_field"] in headers:
        raise TransformationError("Source already contains the output H3 field")
    return [name for name in headers if name]


def evaluate_counts(counts: Counter, policy: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    """Calculate both join rates and return all policy failure reasons."""
    total = counts["source_rows"]
    missing = counts["missing_both"] + counts["missing_one"]
    invalid = counts["nonnumeric"] + counts["nonfinite"] + counts["out_of_range"]
    eligible = total - missing
    gaps = counts["usable_outside_original_grid"]
    counts["original_grid_unjoined_rows"] = missing + invalid + gaps
    counts["unexpected_join_error_rows"] = invalid + gaps
    counts["recovered_coverage_gap_rows"] = gaps
    total_rate = (missing + invalid + gaps) / total if total else 1.0
    unexpected_rate = (invalid + gaps) / eligible if eligible else 1.0
    rates = {
        "original_grid_unjoined_fraction": total_rate,
        "unexpected_join_error_fraction": unexpected_rate,
    }
    failures = []
    if not total:
        failures.append("empty_source")
    if not counts["usable"]:
        failures.append("no_usable_coordinates")
    if counts["source_missing_identity_rows"]:
        failures.append("missing_row_identity")
    if counts["source_duplicate_identity_rows"]:
        failures.append("duplicate_row_identity")
    if counts["unnamed_index_sequence_mismatches"]:
        failures.append("unverified_unnamed_column")
    if invalid:
        failures.append("invalid_coordinates")
    if total_rate > policy["original_grid_unjoined_rate"]["maximum_fraction"]:
        failures.append("original_grid_unjoined_threshold_exceeded")
    if unexpected_rate > policy["unexpected_join_error_rate"]["maximum_fraction"]:
        failures.append("unexpected_join_error_threshold_exceeded")
    return rates, failures


def _cell_feature(cell: str, request_count: int, resolution: int) -> dict[str, Any]:
    ring = [[lon, lat] for lat, lon in h3.cell_to_boundary(cell)]
    ring.append(ring[0])
    return {
        "type": "Feature",
        "properties": {
            "index": cell,
            "resolution": resolution,
            "source": "h3_derived_coverage_gap",
            "h3_python_version": h3.versions()["python"],
            "recovered_request_count": request_count,
        },
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def transform_csv(
    source: csv.DictReader,
    temporary_output: Path,
    allowed_cells: set[str],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Stream source rows into a deterministic temporary gzip CSV."""
    named_headers = _validate_headers(source.fieldnames, policy)
    output_headers = named_headers + [policy["output_index_field"]]
    counts: Counter = Counter(
        {
            name: 0
            for name in (
                "source_rows",
                "source_missing_identity_rows",
                "source_duplicate_identity_rows",
                "unnamed_index_sequence_mismatches",
                "missing_both",
                "missing_one",
                "nonnumeric",
                "nonfinite",
                "out_of_range",
                "usable",
                "usable_in_original_grid",
                "usable_outside_original_grid",
            )
        }
    )
    seen_identities: set[str] = set()
    uncovered_cells: Counter = Counter()
    temporary_output.parent.mkdir(parents=True, exist_ok=True)

    with temporary_output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=output_headers, lineterminator="\n")
                writer.writeheader()
                for row_number, row in enumerate(source):
                    counts["source_rows"] += 1
                    missing_value = any(
                        row.get(name) is None for name in source.fieldnames or []
                    )
                    if None in row or missing_value:
                        raise TransformationError(f"Malformed source row at position {row_number}")
                    if "" in row and row[""] != str(row_number):
                        counts["unnamed_index_sequence_mismatches"] += 1

                    identity = row[policy["row_identity_field"]]
                    counts["source_missing_identity_rows"] += not bool(identity.strip())
                    counts["source_duplicate_identity_rows"] += identity in seen_identities
                    seen_identities.add(identity)

                    category, cell = classify_coordinates(
                        row[policy["latitude_field"]],
                        row[policy["longitude_field"]],
                        policy["resolution"],
                    )
                    counts[category] += 1
                    if category == "usable":
                        in_grid = cell in allowed_cells
                        label = (
                            "usable_in_original_grid"
                            if in_grid
                            else "usable_outside_original_grid"
                        )
                        counts[label] += 1
                        if not in_grid:
                            uncovered_cells[cell] += 1

                    output_row = {name: row[name] for name in named_headers}
                    output_row[policy["output_index_field"]] = cell
                    writer.writerow(output_row)

    rates, failures = evaluate_counts(counts, policy)
    supplemental = {
        "type": "FeatureCollection",
        "features": [
            _cell_feature(cell, count, policy["resolution"])
            for cell, count in sorted(uncovered_cells.items())
        ],
    }
    return {
        "counts": dict(counts),
        "rates": rates,
        "thresholds": {
            "original_grid_unjoined_maximum_fraction": policy[
                "original_grid_unjoined_rate"
            ]["maximum_fraction"],
            "unexpected_join_error_maximum_fraction": policy[
                "unexpected_join_error_rate"
            ]["maximum_fraction"],
        },
        "failure_reasons": failures,
        "supplemental_grid": supplemental,
        "output_headers": output_headers,
        "unique_source_identities": len(seen_identities),
    }


def compare_csv_with_reference(
    produced: csv.DictReader,
    reference: csv.DictReader,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Compare the serialized candidate output to every reference row and field."""
    if produced.fieldnames != reference.fieldnames:
        raise TransformationError("Candidate and reference CSV headers differ")
    if not produced.fieldnames or policy["output_index_field"] not in produced.fieldnames:
        raise TransformationError("Candidate output has no H3 index field")
    counts: Counter = Counter(
        {
            "unpaired_rows": 0,
            "paired_rows": 0,
            "mismatched_rows": 0,
            "identity_mismatches": 0,
            "h3_mismatches": 0,
        }
    )
    field_mismatches: Counter = Counter()
    for produced_row, reference_row in zip_longest(produced, reference):
        if produced_row is None or reference_row is None:
            counts["unpaired_rows"] += 1
            continue
        counts["paired_rows"] += 1
        different = [
            name for name in produced.fieldnames if produced_row[name] != reference_row[name]
        ]
        field_mismatches.update(different)
        counts["mismatched_rows"] += bool(different)
        counts["identity_mismatches"] += (
            produced_row[policy["row_identity_field"]]
            != reference_row[policy["row_identity_field"]]
        )
        counts["h3_mismatches"] += (
            produced_row[policy["output_index_field"]]
            != reference_row[policy["output_index_field"]]
        )

    limits = policy["reference_validation"]
    passed = (
        counts["unpaired_rows"] <= limits["allowed_unpaired_rows"]
        and counts["identity_mismatches"] <= limits["allowed_identity_mismatches"]
        and counts["mismatched_rows"] <= limits["allowed_shared_value_mismatches"]
        and counts["h3_mismatches"] <= limits["allowed_h3_mismatches"]
        and counts["paired_rows"] > 0
    )
    return {
        "passed": passed,
        "counts": dict(counts),
        "field_mismatch_counts": dict(field_mismatches),
    }


def open_local_gzip_csv(path: Path) -> TextIO:
    """Open a local gzip CSV text stream."""
    return gzip.open(path, mode="rt", encoding="utf-8-sig", newline="")


def sha256_file(path: Path) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
