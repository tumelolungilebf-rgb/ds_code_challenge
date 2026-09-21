"""Tests for publication behavior in the Section 1 orchestrator."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h3

from yearbeyond_pipeline.extract import SelectExtraction
from yearbeyond_pipeline.pipeline import run_section1

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT_ROOT / "config" / "h3_level8_schema.json"


def feature(*, resolution: int = 8, include_resolution: bool = True) -> dict:
    """Return one valid synthetic feature, optionally without source resolution."""
    properties = {
        "index": h3.latlng_to_cell(-33.92, 18.42, 8),
        "centroid_lat": -33.92,
        "centroid_lon": 18.42,
    }
    if include_resolution:
        properties["resolution"] = resolution
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


def quiet_logger() -> logging.Logger:
    """Create a logger that does not write test output."""
    logger = logging.getLogger("yearbeyond.test.pipeline")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


class PipelinePublicationTests(unittest.TestCase):
    def run_with_feature(self, source_feature: dict, directory: Path) -> tuple[dict, Path, Path]:
        output_path = directory / "result.geojson"
        report_path = directory / "report.json"
        reference = {
            "type": "FeatureCollection",
            "features": [feature(include_resolution=False)],
        }
        metadata = {
            "object_key": "test",
            "size_bytes": 1,
            "etag": '"etag"',
            "last_modified": "2026-01-01T00:00:00+00:00",
            "version_id": None,
        }
        extraction = SelectExtraction(
            features=[source_feature], statistics={"BytesScanned": 100}
        )
        with (
            patch(
                "yearbeyond_pipeline.pipeline.get_object_metadata",
                return_value=metadata,
            ),
            patch(
                "yearbeyond_pipeline.pipeline.extract_level8_features",
                return_value=extraction,
            ),
            patch(
                "yearbeyond_pipeline.pipeline.read_json_object",
                return_value=reference,
            ),
        ):
            report = run_section1(
                client=object(),
                contract_path=CONTRACT_PATH,
                output_path=output_path,
                report_path=report_path,
                logger=quiet_logger(),
            )
        return report, output_path, report_path

    def test_publishes_output_only_after_both_validations_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            report, output_path, report_path = self.run_with_feature(
                feature(), Path(directory_name)
            )

            self.assertEqual(report["status"], "passed")
            self.assertTrue(report["output_published"])
            self.assertTrue(output_path.exists())
            self.assertEqual(json.loads(output_path.read_text())["type"], "FeatureCollection")
            self.assertEqual(json.loads(report_path.read_text())["status"], "passed")

    def test_failure_does_not_replace_existing_successful_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            output_path = directory / "result.geojson"
            output_path.write_text("previous-good-output", encoding="utf-8")

            report, output_path, report_path = self.run_with_feature(
                feature(resolution=9), directory
            )

            self.assertEqual(report["status"], "failed")
            self.assertFalse(report["output_published"])
            self.assertTrue(report["output_existed_before_run"])
            self.assertEqual(output_path.read_text(encoding="utf-8"), "previous-good-output")
            saved_report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIn("schema_validation_failed", saved_report["failure_reasons"])


if __name__ == "__main__":
    unittest.main()
