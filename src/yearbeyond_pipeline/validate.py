"""Schema scoring and reference comparison for Section 1 GeoJSON."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import h3

SUPPORTED_CHECKS = {
    "feature_structure",
    "h3_index",
    "resolution",
    "polygon_structure",
    "centroid_latitude",
    "centroid_longitude",
}
MISSING = object()


class ContractError(ValueError):
    """Raised when the standalone validation contract is unsupported."""


def load_contract(path: Path) -> dict[str, Any]:
    """Load and validate the parts of the contract used by this implementation."""
    contract = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict) or contract.get("contract_version") != 1:
        raise ContractError("Only contract_version 1 is supported")

    checks = contract.get("feature_checks")
    if not isinstance(checks, list) or not checks:
        raise ContractError("feature_checks must be a nonempty list")
    check_ids = [check.get("id") for check in checks if isinstance(check, dict)]
    if len(check_ids) != len(checks) or len(set(check_ids)) != len(check_ids):
        raise ContractError("Feature check IDs must be present and unique")
    if set(check_ids) != SUPPORTED_CHECKS:
        raise ContractError("Contract feature checks do not match supported checks")

    threshold = contract.get("scoring", {}).get("minimum_percent")
    if not _is_number(threshold) or not 0 <= threshold <= 100:
        raise ContractError("minimum_percent must be a number between 0 and 100")
    if contract.get("collection", {}).get("unique_key") != "properties.index":
        raise ContractError("Only properties.index is supported as the unique key")
    return contract


def _is_number(value: Any) -> bool:
    """Accept finite JSON numbers while excluding Python booleans."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _valid_bounded_number(value: Any, bounds: list[float]) -> bool:
    """Validate a finite numeric value against inclusive bounds."""
    return _is_number(value) and bounds[0] <= value <= bounds[1]


def _valid_h3_index(value: Any, expected_resolution: int) -> bool:
    """Validate an H3 cell and its encoded resolution through the H3 library."""
    if not isinstance(value, str) or not value:
        return False
    try:
        return h3.is_valid_cell(value) and h3.get_resolution(value) == expected_resolution
    except (TypeError, ValueError):
        return False


def _valid_polygon(geometry: Any, rule: dict[str, Any]) -> bool:
    """Validate the structural subset of GeoJSON Polygon required by the contract."""
    if not isinstance(geometry, dict) or geometry.get("type") != rule["type"]:
        return False
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < rule["minimum_rings"]:
        return False

    longitude_bounds = rule["longitude_bounds"]
    latitude_bounds = rule["latitude_bounds"]
    dimensions = rule["position_dimensions"]
    for ring in coordinates:
        if not isinstance(ring, list) or len(ring) < rule["minimum_positions_per_ring"]:
            return False
        if rule["closed_rings"] and ring[0] != ring[-1]:
            return False
        for position in ring:
            if not isinstance(position, list) or len(position) != dimensions:
                return False
            longitude, latitude = position
            if not _valid_bounded_number(longitude, longitude_bounds):
                return False
            if not _valid_bounded_number(latitude, latitude_bounds):
                return False
    return True


def _evaluate_feature(
    feature: Any, checks_by_id: dict[str, dict[str, Any]]
) -> dict[str, bool]:
    """Evaluate every configured check; missing parents fail dependent checks."""
    properties = feature.get("properties") if isinstance(feature, dict) else None
    geometry = feature.get("geometry") if isinstance(feature, dict) else None
    structure_ok = (
        isinstance(feature, dict)
        and feature.get("type") == "Feature"
        and isinstance(properties, dict)
        and isinstance(geometry, dict)
    )

    index_value = properties.get("index") if isinstance(properties, dict) else None
    resolution_value = (
        properties.get("resolution") if isinstance(properties, dict) else None
    )
    centroid_latitude = (
        properties.get("centroid_lat") if isinstance(properties, dict) else None
    )
    centroid_longitude = (
        properties.get("centroid_lon") if isinstance(properties, dict) else None
    )
    resolution_rule = checks_by_id["resolution"]
    return {
        "feature_structure": structure_ok,
        "h3_index": _valid_h3_index(
            index_value, checks_by_id["h3_index"]["h3_resolution"]
        ),
        "resolution": (
            type(resolution_value) is int
            and resolution_value == resolution_rule["value"]
        ),
        "polygon_structure": _valid_polygon(
            geometry, checks_by_id["polygon_structure"]
        ),
        "centroid_latitude": _valid_bounded_number(
            centroid_latitude, checks_by_id["centroid_latitude"]["bounds"]
        ),
        "centroid_longitude": _valid_bounded_number(
            centroid_longitude, checks_by_id["centroid_longitude"]["bounds"]
        ),
    }


def validate_collection(
    collection: Any, contract: dict[str, Any]
) -> dict[str, Any]:
    """Calculate the non-binary conformance score and mandatory failure gates."""
    configured_checks = contract["feature_checks"]
    checks_by_id = {check["id"]: check for check in configured_checks}
    threshold = contract["scoring"]["minimum_percent"]
    collection_rule = contract["collection"]
    collection_valid = (
        isinstance(collection, dict)
        and collection.get("type") == collection_rule["type"]
        and isinstance(collection.get("features"), list)
        and len(collection["features"]) >= collection_rule["minimum_features"]
    )
    if not collection_valid:
        return {
            "passed": False,
            "collection_valid": False,
            "feature_count": 0,
            "fully_conformant_features": 0,
            "passed_checks": 0,
            "total_checks": 0,
            "score_percent": contract["scoring"]["empty_or_invalid_collection_score"],
            "threshold_percent": threshold,
            "score_passed": False,
            "critical_failure_count": 0,
            "duplicate_index_count": 0,
            "duplicate_index_examples": [],
            "additional_property_names": [],
            "rule_results": [],
            "error": "Invalid or empty FeatureCollection",
        }

    features = collection["features"]
    rule_failures = Counter({check["id"]: 0 for check in configured_checks})
    fully_conformant = 0
    indices: list[str] = []
    additional_property_names: set[str] = set()
    expected_properties = {"index", "resolution", "centroid_lat", "centroid_lon"}

    for feature in features:
        results = _evaluate_feature(feature, checks_by_id)
        if all(results.values()):
            fully_conformant += 1
        for check_id, passed in results.items():
            if not passed:
                rule_failures[check_id] += 1

        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict):
            properties = feature["properties"]
            additional_property_names.update(set(properties) - expected_properties)
            if isinstance(properties.get("index"), str):
                indices.append(properties["index"])

    index_counts = Counter(indices)
    duplicate_indices = sorted(
        index for index, count in index_counts.items() if count > 1
    )
    total_checks = len(features) * len(configured_checks)
    failed_checks = sum(rule_failures.values())
    passed_checks = total_checks - failed_checks
    score = 100 * passed_checks / total_checks
    critical_failure_count = sum(
        rule_failures[check["id"]] for check in configured_checks if check["critical"]
    )
    score_passed = score >= threshold
    passed = score_passed and critical_failure_count == 0 and not duplicate_indices

    return {
        "passed": passed,
        "collection_valid": True,
        "feature_count": len(features),
        "fully_conformant_features": fully_conformant,
        "passed_checks": passed_checks,
        "total_checks": total_checks,
        "score_percent": score,
        "score_percent_display": round(score, 4),
        "threshold_percent": threshold,
        "score_passed": score_passed,
        "critical_failure_count": critical_failure_count,
        "duplicate_index_count": len(duplicate_indices),
        "duplicate_index_examples": duplicate_indices[:20],
        "additional_property_names": sorted(additional_property_names),
        "rule_results": [
            {
                "id": check["id"],
                "critical": check["critical"],
                "passed_count": len(features) - rule_failures[check["id"]],
                "failed_count": rule_failures[check["id"]],
            }
            for check in configured_checks
        ],
    }


def _get_path(value: Any, path: str) -> Any:
    """Read a dotted object path and distinguish missing from explicit null."""
    current = value
    for component in path.split("."):
        if not isinstance(current, dict) or component not in current:
            return MISSING
        current = current[component]
    return current


def _values_equal(left: Any, right: Any, absolute_tolerance: float) -> bool:
    """Compare nested values with a strict absolute tolerance for numbers."""
    if left is MISSING or right is MISSING:
        return left is right
    if _is_number(left) and _is_number(right):
        return math.isclose(left, right, rel_tol=0, abs_tol=absolute_tolerance)
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _values_equal(a, b, absolute_tolerance) for a, b in zip(left, right)
        )
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _values_equal(left[key], right[key], absolute_tolerance) for key in left
        )
    return left == right


def _index_features(
    collection: Any, expected_resolution: int
) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    """Index valid features without silently overwriting duplicate keys."""
    if (
        not isinstance(collection, dict)
        or collection.get("type") != "FeatureCollection"
        or not isinstance(collection.get("features"), list)
    ):
        return {}, [], ["Invalid FeatureCollection"]
    indexed: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    issues: list[str] = []
    for position, feature in enumerate(collection["features"]):
        index = _get_path(feature, "properties.index")
        if not _valid_h3_index(index, expected_resolution):
            issues.append(f"Feature {position} has an invalid level-{expected_resolution} index")
            continue
        if index in indexed:
            duplicates.add(index)
            continue
        indexed[index] = feature
    return indexed, sorted(duplicates), issues


def compare_with_reference(
    extracted: Any, reference: Any, contract: dict[str, Any]
) -> dict[str, Any]:
    """Compare extracted features with the independent supplied reference by H3 key."""
    comparison = contract["reference_comparison"]
    expected_resolution = next(
        check["h3_resolution"]
        for check in contract["feature_checks"]
        if check["id"] == "h3_index"
    )
    source_by_index, source_duplicates, source_issues = _index_features(
        extracted, expected_resolution
    )
    reference_by_index, reference_duplicates, reference_issues = _index_features(
        reference, expected_resolution
    )
    source_keys = set(source_by_index)
    reference_keys = set(reference_by_index)
    missing_indices = sorted(reference_keys - source_keys)
    extra_indices = sorted(source_keys - reference_keys)
    tolerance = comparison["numeric_absolute_tolerance"]
    mismatch_examples: list[dict[str, Any]] = []
    mismatched_features = 0

    for index in sorted(source_keys & reference_keys):
        failed_paths = [
            path
            for path in comparison["compare_paths"]
            if not _values_equal(
                _get_path(source_by_index[index], path),
                _get_path(reference_by_index[index], path),
                tolerance,
            )
        ]
        if failed_paths:
            mismatched_features += 1
            if len(mismatch_examples) < 20:
                mismatch_examples.append({"index": index, "paths": failed_paths})

    passed = (
        not source_duplicates
        and not reference_duplicates
        and not source_issues
        and not reference_issues
        and not missing_indices
        and not extra_indices
        and mismatched_features <= comparison["allowed_mismatched_features"]
    )
    return {
        "passed": passed,
        "extracted_index_count": len(source_by_index),
        "reference_index_count": len(reference_by_index),
        "missing_index_count": len(missing_indices),
        "missing_index_examples": missing_indices[:20],
        "extra_index_count": len(extra_indices),
        "extra_index_examples": extra_indices[:20],
        "extracted_duplicate_count": len(source_duplicates),
        "extracted_duplicate_examples": source_duplicates[:20],
        "reference_duplicate_count": len(reference_duplicates),
        "reference_duplicate_examples": reference_duplicates[:20],
        "extracted_index_issue_count": len(source_issues),
        "extracted_index_issue_examples": source_issues[:20],
        "reference_index_issue_count": len(reference_issues),
        "reference_index_issue_examples": reference_issues[:20],
        "mismatched_feature_count": mismatched_features,
        "mismatch_examples": mismatch_examples,
        "compared_paths": comparison["compare_paths"],
        "numeric_absolute_tolerance": tolerance,
    }
