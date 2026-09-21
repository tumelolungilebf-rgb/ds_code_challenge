"""Focused tests for the Section 2 streaming transformation."""

from __future__ import annotations

import copy
import csv
import gzip
import io
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import h3

from yearbeyond_pipeline.transform import (
    classify_coordinates,
    compare_csv_with_reference,
    evaluate_counts,
    load_policy,
    sha256_file,
    transform_csv,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY = load_policy(PROJECT_ROOT / "config" / "section2_policy.json")
CENTER = h3.latlng_to_cell(-33.92, 18.42, 8)
OUTSIDE = next(iter(set(h3.grid_disk(CENTER, 2)) - set(h3.grid_disk(CENTER, 1))))


def reader(text: str) -> csv.DictReader:
    return csv.DictReader(io.StringIO(text, newline=""))


class CoordinateClassificationTests(unittest.TestCase):
    def test_coordinate_categories_are_explicit(self) -> None:
        cases = {
            ("", ""): "missing_both",
            ("-33.9", ""): "missing_one",
            ("south", "18.4"): "nonnumeric",
            ("nan", "18.4"): "nonfinite",
            ("-91", "18.4"): "out_of_range",
            ("-33.92", "18.42"): "usable",
        }
        for coordinates, expected in cases.items():
            with self.subTest(coordinates=coordinates):
                category, _ = classify_coordinates(*coordinates, resolution=8)
                self.assertEqual(category, expected)


class StreamingTransformationTests(unittest.TestCase):
    def test_preserves_rows_assigns_zero_and_derives_uncovered_cell(self) -> None:
        policy = copy.deepcopy(POLICY)
        policy["original_grid_unjoined_rate"]["maximum_fraction"] = 1
        policy["unexpected_join_error_rate"]["maximum_fraction"] = 1
        outside_lat, outside_lon = h3.cell_to_latlng(OUTSIDE)
        source_text = (
            ",notification_number,latitude,longitude\n"
            "0,A,-33.92,18.42\n"
            "1,B,,\n"
            f"2,C,{outside_lat},{outside_lon}\n"
        )

        with tempfile.TemporaryDirectory() as directory_name:
            first = Path(directory_name) / "first.csv.gz"
            second = Path(directory_name) / "second.csv.gz"
            first_result = transform_csv(reader(source_text), first, {CENTER}, policy)
            second_result = transform_csv(reader(source_text), second, {CENTER}, policy)

            with gzip.open(first, "rt", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))

            self.assertEqual(len(rows), 3)
            self.assertNotIn("", rows[0])
            self.assertEqual(rows[0]["h3_level8_index"], CENTER)
            self.assertEqual(rows[1]["h3_level8_index"], "0")
            self.assertEqual(rows[2]["h3_level8_index"], OUTSIDE)
            self.assertEqual(first_result["counts"]["usable_outside_original_grid"], 1)
            feature = first_result["supplemental_grid"]["features"][0]
            self.assertEqual(feature["properties"]["index"], OUTSIDE)
            self.assertEqual(feature["properties"]["source"], "h3_derived_coverage_gap")
            self.assertEqual(feature["geometry"]["coordinates"][0][0],
                             feature["geometry"]["coordinates"][0][-1])
            self.assertEqual(sha256_file(first), sha256_file(second))
            self.assertEqual(first_result["failure_reasons"], second_result["failure_reasons"])

    def test_malformed_coordinates_fail_independently_of_thresholds(self) -> None:
        policy = copy.deepcopy(POLICY)
        policy["original_grid_unjoined_rate"]["maximum_fraction"] = 1
        policy["unexpected_join_error_rate"]["maximum_fraction"] = 1
        source_text = (
            ",notification_number,latitude,longitude\n"
            "0,A,-33.92,18.42\n"
            "1,B,not-a-number,18.42\n"
        )
        with tempfile.TemporaryDirectory() as directory_name:
            result = transform_csv(
                reader(source_text), Path(directory_name) / "candidate.gz", {CENTER}, policy
            )
        self.assertIn("invalid_coordinates", result["failure_reasons"])

    def test_unverified_unnamed_column_fails(self) -> None:
        source_text = (
            ",notification_number,latitude,longitude\n"
            "7,A,-33.92,18.42\n"
        )
        with tempfile.TemporaryDirectory() as directory_name:
            result = transform_csv(
                reader(source_text), Path(directory_name) / "candidate.gz", {CENTER}, POLICY
            )
        self.assertIn("unverified_unnamed_column", result["failure_reasons"])

    def test_threshold_boundary_passes_and_next_row_fails(self) -> None:
        total_exact = Counter(source_rows=100, usable=75, missing_both=25)
        rates, failures = evaluate_counts(total_exact, POLICY)
        self.assertEqual(rates["original_grid_unjoined_fraction"], 0.25)
        self.assertNotIn("original_grid_unjoined_threshold_exceeded", failures)

        total_above = Counter(source_rows=100, usable=74, missing_both=26)
        _, failures = evaluate_counts(total_above, POLICY)
        self.assertIn("original_grid_unjoined_threshold_exceeded", failures)

        exact_counts = Counter(
            source_rows=100_000,
            usable=100_000,
            usable_outside_original_grid=1,
        )
        rates, failures = evaluate_counts(exact_counts, POLICY)
        self.assertEqual(rates["unexpected_join_error_fraction"], 0.00001)
        self.assertNotIn("unexpected_join_error_threshold_exceeded", failures)

        above_counts = Counter(
            source_rows=100_000,
            usable=100_000,
            usable_outside_original_grid=2,
        )
        _, failures = evaluate_counts(above_counts, POLICY)
        self.assertIn("unexpected_join_error_threshold_exceeded", failures)


class ReferenceComparisonTests(unittest.TestCase):
    def test_exact_candidate_passes(self) -> None:
        text = (
            "notification_number,latitude,longitude,h3_level8_index\n"
            f"A,-33.92,18.42,{CENTER}\n"
        )
        result = compare_csv_with_reference(reader(text), reader(text), POLICY)
        self.assertTrue(result["passed"])
        self.assertEqual(result["counts"]["paired_rows"], 1)

    def test_reordered_or_changed_reference_fails(self) -> None:
        candidate = (
            "notification_number,latitude,longitude,h3_level8_index\n"
            f"A,-33.92,18.42,{CENTER}\n"
            f"B,-33.92,18.42,{CENTER}\n"
        )
        reference = (
            "notification_number,latitude,longitude,h3_level8_index\n"
            f"B,-33.92,18.42,{CENTER}\n"
            f"A,-33.92,18.42,{CENTER}\n"
        )
        result = compare_csv_with_reference(reader(candidate), reader(reference), POLICY)
        self.assertFalse(result["passed"])
        self.assertEqual(result["counts"]["identity_mismatches"], 2)


if __name__ == "__main__":
    unittest.main()
