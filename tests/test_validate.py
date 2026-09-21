"""Tests for graded schema validation and reference comparison."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

import h3

from yearbeyond_pipeline.validate import (
    compare_with_reference,
    load_contract,
    validate_collection,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = load_contract(PROJECT_ROOT / "config" / "h3_level8_schema.json")
CENTER_CELL = h3.latlng_to_cell(-33.92, 18.42, 8)
TEST_CELLS = sorted(h3.grid_disk(CENTER_CELL, 7))


def make_feature(index: str, *, include_resolution: bool = True) -> dict:
    """Create a small structurally valid feature for deterministic tests."""
    properties = {
        "index": index,
        "centroid_lat": -33.92,
        "centroid_lon": 18.42,
    }
    if include_resolution:
        properties["resolution"] = 8
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [18.41, -33.93],
                    [18.43, -33.93],
                    [18.43, -33.91],
                    [18.41, -33.91],
                    [18.41, -33.93],
                ]
            ],
        },
    }


def collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


class SchemaValidationTests(unittest.TestCase):
    def test_valid_collection_scores_100(self) -> None:
        report = validate_collection(collection([make_feature(TEST_CELLS[0])]), CONTRACT)

        self.assertTrue(report["passed"])
        self.assertEqual(report["score_percent"], 100)
        self.assertEqual(report["fully_conformant_features"], 1)

    def test_exact_995_threshold_passes(self) -> None:
        features = [make_feature(index) for index in TEST_CELLS[:100]]
        for feature in features[:3]:
            feature["properties"].pop("centroid_lat")

        report = validate_collection(collection(features), CONTRACT)

        self.assertEqual(report["score_percent"], 99.5)
        self.assertTrue(report["passed"])

    def test_four_auxiliary_failures_fall_below_threshold(self) -> None:
        features = [make_feature(index) for index in TEST_CELLS[:100]]
        for feature in features[:4]:
            feature["properties"].pop("centroid_lat")

        report = validate_collection(collection(features), CONTRACT)

        self.assertLess(report["score_percent"], 99.5)
        self.assertFalse(report["passed"])

    def test_critical_failure_overrides_high_score(self) -> None:
        features = [make_feature(index) for index in TEST_CELLS[:100]]
        features[0]["properties"]["resolution"] = 9

        report = validate_collection(collection(features), CONTRACT)

        self.assertGreater(report["score_percent"], 99.5)
        self.assertEqual(report["critical_failure_count"], 1)
        self.assertFalse(report["passed"])

    def test_duplicate_index_fails(self) -> None:
        features = [make_feature(TEST_CELLS[0]), make_feature(TEST_CELLS[0])]

        report = validate_collection(collection(features), CONTRACT)

        self.assertEqual(report["duplicate_index_count"], 1)
        self.assertFalse(report["passed"])

    def test_boolean_centroid_is_not_a_number(self) -> None:
        feature = make_feature(TEST_CELLS[0])
        feature["properties"]["centroid_lat"] = True

        report = validate_collection(collection([feature]), CONTRACT)

        latitude_result = next(
            item for item in report["rule_results"] if item["id"] == "centroid_latitude"
        )
        self.assertEqual(latitude_result["failed_count"], 1)

    def test_open_polygon_is_critical_failure(self) -> None:
        feature = make_feature(TEST_CELLS[0])
        feature["geometry"]["coordinates"][0][-1] = [18.40, -33.93]

        report = validate_collection(collection([feature]), CONTRACT)

        self.assertEqual(report["critical_failure_count"], 1)
        self.assertFalse(report["passed"])

    def test_empty_collection_scores_zero(self) -> None:
        report = validate_collection(collection([]), CONTRACT)

        self.assertEqual(report["score_percent"], 0)
        self.assertFalse(report["passed"])


class ReferenceComparisonTests(unittest.TestCase):
    def source_and_reference(self) -> tuple[dict, dict]:
        source_features = [make_feature(index) for index in TEST_CELLS[:3]]
        reference_features = [
            make_feature(index, include_resolution=False) for index in reversed(TEST_CELLS[:3])
        ]
        return collection(source_features), collection(reference_features)

    def test_feature_order_does_not_affect_comparison(self) -> None:
        source, reference = self.source_and_reference()

        report = compare_with_reference(source, reference, CONTRACT)

        self.assertTrue(report["passed"])

    def test_equal_counts_with_different_indices_fail(self) -> None:
        source, reference = self.source_and_reference()
        reference["features"][0] = make_feature(
            TEST_CELLS[10], include_resolution=False
        )

        report = compare_with_reference(source, reference, CONTRACT)

        self.assertFalse(report["passed"])
        self.assertEqual(report["missing_index_count"], 1)
        self.assertEqual(report["extra_index_count"], 1)

    def test_small_numeric_serialization_difference_is_tolerated(self) -> None:
        source, reference = self.source_and_reference()
        reference["features"][0]["properties"]["centroid_lat"] += 5e-10

        report = compare_with_reference(source, reference, CONTRACT)

        self.assertTrue(report["passed"])

    def test_material_numeric_difference_fails(self) -> None:
        source, reference = self.source_and_reference()
        reference["features"][0]["properties"]["centroid_lat"] += 2e-9

        report = compare_with_reference(source, reference, CONTRACT)

        self.assertFalse(report["passed"])
        self.assertEqual(report["mismatched_feature_count"], 1)

    def test_geometry_change_fails(self) -> None:
        source, reference = self.source_and_reference()
        reference["features"][0]["geometry"]["coordinates"][0][1][0] += 0.01

        report = compare_with_reference(source, reference, CONTRACT)

        self.assertFalse(report["passed"])
        self.assertEqual(report["mismatched_feature_count"], 1)

    def test_reference_duplicate_is_reported(self) -> None:
        source, reference = self.source_and_reference()
        reference["features"].append(copy.deepcopy(reference["features"][0]))

        report = compare_with_reference(source, reference, CONTRACT)

        self.assertEqual(report["reference_duplicate_count"], 1)
        self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
