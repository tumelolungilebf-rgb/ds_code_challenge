"""Measure candidate Section 2 joins without producing a transformed dataset.

Run after installing the package and completing Section 1. Only aggregate
statistics are saved; resident-level records and identifiers are not emitted.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime
from itertools import zip_longest
from pathlib import Path
from time import perf_counter

import h3

from yearbeyond_pipeline.pipeline import atomic_write_json
from yearbeyond_pipeline.sources import BUCKET, create_s3_client, get_object_metadata

ROOT = Path(__file__).resolve().parents[1]
OBJECTS = ("sr.csv.gz", "sr_hex.csv.gz")


def classify_coordinates(latitude: str, longitude: str) -> tuple[str, str]:
    """Classify CSV coordinates and calculate a candidate cell independently."""
    if not latitude.strip() or not longitude.strip():
        both_missing = not latitude.strip() and not longitude.strip()
        category = "missing_both" if both_missing else "missing_one"
        return category, "0"
    try:
        lat, lon = float(latitude), float(longitude)
    except ValueError:
        return "nonnumeric", "0"
    if not math.isfinite(lat) or not math.isfinite(lon):
        return "nonfinite", "0"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return "out_of_range", "0"
    return "usable", h3.latlng_to_cell(lat, lon, 8)


def same_boundary(ring: list, cell: str) -> bool:
    """Compare supplied vertices to H3, allowing cyclic order and reversal."""
    if not ring or ring[0] != ring[-1]:
        return False
    actual = ring[:-1]
    expected = [[lon, lat] for lat, lon in h3.cell_to_boundary(cell)]
    if len(actual) != len(expected):
        return False
    for order in (expected, list(reversed(expected))):
        for offset in range(len(order)):
            if all(
                all(abs(a - b) <= 1e-9 for a, b in zip(point, order[(i + offset) % len(order)]))
                for i, point in enumerate(actual)
            ):
                return True
    return False


def inspect(grid_path: Path) -> dict:
    """Compare source and reference streams, recording only aggregate evidence."""
    started = perf_counter()
    grid_bytes = grid_path.read_bytes()
    grid = json.loads(grid_bytes)
    if grid.get("type") != "FeatureCollection" or not grid.get("features"):
        raise ValueError("A nonempty FeatureCollection is required")
    grid_cells = [feature["properties"]["index"] for feature in grid["features"]]
    if len(set(grid_cells)) != len(grid_cells):
        raise ValueError("Duplicate indices in grid")
    if not all(h3.is_valid_cell(cell) and h3.get_resolution(cell) == 8 for cell in grid_cells):
        raise ValueError("Invalid or non-level-8 grid index")
    allowed_cells = set(grid_cells)
    boundary_mismatches = sum(
        feature["geometry"]["type"] != "Polygon"
        or len(feature["geometry"]["coordinates"]) != 1
        or not same_boundary(feature["geometry"]["coordinates"][0], feature["properties"]["index"])
        for feature in grid["features"]
    )
    client = create_s3_client()
    before = {key: get_object_metadata(client, key) for key in OBJECTS}
    counts = Counter({name: 0 for name in (
        "source_rows", "reference_rows", "paired_rows", "unpaired_rows",
        "shared_field_mismatch_rows", "notification_alignment_mismatches",
        "source_duplicate_notification_rows", "source_missing_notification_rows",
        "source_unnamed_index_sequence_mismatches", "missing_both", "missing_one",
        "nonnumeric", "nonfinite", "out_of_range", "usable", "usable_in_grid",
        "usable_outside_grid", "direct_h3_reference_mismatches",
        "grid_join_reference_mismatches", "reference_zero", "reference_invalid_h3",
        "reference_nonzero_outside_grid", "missing_coordinate_reference_nonzero",
    )})
    field_differences: Counter = Counter()
    seen_notifications: set[str] = set()
    used_cells: set[str] = set()
    uncovered_cells: Counter = Counter()
    with ExitStack() as stack:
        readers = []
        for key in OBJECTS:
            body = client.get_object(Bucket=BUCKET, Key=key)["Body"]
            stack.callback(body.close)
            compressed = stack.enter_context(gzip.GzipFile(fileobj=body))
            text = stack.enter_context(io.TextIOWrapper(compressed, encoding="utf-8-sig", newline=""))
            reader = csv.DictReader(text)
            headers = reader.fieldnames
            if not headers or len(headers) != len(set(headers)):
                raise ValueError("Missing or duplicate CSV header")
            required = {"notification_number", "latitude", "longitude"}
            if key == "sr_hex.csv.gz":
                required.add("h3_level8_index")
            if not required <= set(headers):
                raise ValueError(f"Missing required fields in {key}")
            readers.append(reader)
        source_headers, reference_headers = (reader.fieldnames for reader in readers)
        shared = sorted(set(source_headers) & set(reference_headers))
        for row_number, (source, reference) in enumerate(zip_longest(*readers)):
            for label, row, headers in (
                ("source", source, source_headers), ("reference", reference, reference_headers)
            ):
                if row is not None:
                    counts[f"{label}_rows"] += 1
                    if None in row or any(row.get(name) is None for name in headers):
                        raise ValueError(f"Malformed {label} CSV row at position {row_number}")
            if source is None or reference is None:
                counts["unpaired_rows"] += 1
                continue
            counts["paired_rows"] += 1
            different = [name for name in shared if source[name] != reference[name]]
            field_differences.update(different)
            counts["shared_field_mismatch_rows"] += bool(different)
            counts["notification_alignment_mismatches"] += (
                source["notification_number"] != reference["notification_number"]
            )
            identifier = source["notification_number"]
            counts["source_missing_notification_rows"] += not bool(identifier.strip())
            counts["source_duplicate_notification_rows"] += identifier in seen_notifications
            seen_notifications.add(identifier)
            if "" in source:
                counts["source_unnamed_index_sequence_mismatches"] += source[""] != str(row_number)

            category, direct_cell = classify_coordinates(source["latitude"], source["longitude"])
            counts[category] += 1
            if category == "usable":
                inside = direct_cell in allowed_cells
                counts["usable_in_grid" if inside else "usable_outside_grid"] += 1
                if not inside:
                    uncovered_cells[direct_cell] += 1
                used_cells.add(direct_cell)
            joined_cell = direct_cell if direct_cell in allowed_cells else "0"
            expected = reference["h3_level8_index"]
            counts["direct_h3_reference_mismatches"] += direct_cell != expected
            counts["grid_join_reference_mismatches"] += joined_cell != expected
            counts["reference_zero"] += expected == "0"
            if expected != "0":
                counts["reference_invalid_h3"] += not (
                    h3.is_valid_cell(expected) and h3.get_resolution(expected) == 8
                )
                counts["reference_nonzero_outside_grid"] += expected not in allowed_cells
            if category.startswith("missing_"):
                counts["missing_coordinate_reference_nonzero"] += expected != "0"
            if (row_number + 1) % 200000 == 0:
                print(f"Compared {row_number + 1:,} rows (no row values logged).", flush=True)

    after = {key: get_object_metadata(client, key) for key in OBJECTS}
    if before != after:
        raise RuntimeError("Source metadata changed during inspection; rerun required")
    return {
        "purpose": "Exploratory Section 2 evidence; not a production transformation",
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "h3_versions": h3.versions(),
        "grid_sha256": hashlib.sha256(grid_bytes).hexdigest(),
        "grid_features": len(grid_cells),
        "grid_boundary_mismatches_at_1e_minus_9_degrees": boundary_mismatches,
        "source_headers": source_headers,
        "reference_headers": reference_headers,
        "shared_fields_compared_as_exact_strings": shared,
        "counts": dict(counts),
        "field_mismatch_counts": dict(field_differences),
        "unique_source_notifications": len(seen_notifications),
        "unique_calculated_cells": len(used_cells),
        "uncovered_cell_summary": [
            {
                "cell": cell,
                "request_count": count,
                "adjacent_supplied_cells": len((set(h3.grid_disk(cell, 1)) - {cell}) & allowed_cells),
            }
            for cell, count in sorted(uncovered_cells.items())
        ],
        "sources_unchanged": True,
        "source_metadata": before,
        "elapsed_seconds": round(perf_counter() - started, 6),
        "raw_records_included": False,
        "comparison_note": (
            "Comparisons use row order; shared-field and notification alignment "
            "counts must be zero to support that pairing."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grid", type=Path, default=ROOT / "data/processed/city-hex-polygons-8.geojson"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "docs/section2_probe.json")
    args = parser.parse_args()
    report = inspect(args.grid)
    atomic_write_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
