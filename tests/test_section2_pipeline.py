"""Publication tests for the complete Section 2 orchestrator."""

from __future__ import annotations

import gzip
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path

import h3

from yearbeyond_pipeline.section2_pipeline import run_section2
from yearbeyond_pipeline.sources import (
    SERVICE_REQUEST_OBJECT,
    SERVICE_REQUEST_REFERENCE_OBJECT,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "config" / "section2_policy.json"
CELL = h3.latlng_to_cell(-33.92, 18.42, 8)


def compressed(text: str) -> bytes:
    destination = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=destination, mtime=0) as stream:
        stream.write(text.encode("utf-8"))
    return destination.getvalue()


class FakeS3Client:
    def __init__(self, reference_cell: str = CELL) -> None:
        self.objects = {
            SERVICE_REQUEST_OBJECT: compressed(
                ",notification_number,latitude,longitude\n"
                "0,A,-33.92,18.42\n"
            ),
            SERVICE_REQUEST_REFERENCE_OBJECT: compressed(
                "notification_number,latitude,longitude,h3_level8_index\n"
                f"A,-33.92,18.42,{reference_cell}\n"
            ),
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        return {
            "ContentLength": len(self.objects[Key]),
            "ETag": f'"{Key}"',
        }


def quiet_logger() -> logging.Logger:
    logger = logging.getLogger("yearbeyond.test.section2")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def write_grid(path: Path) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"index": CELL},
                "geometry": {"type": "Polygon", "coordinates": []},
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class Section2PublicationTests(unittest.TestCase):
    def run_pipeline(self, directory: Path, client: FakeS3Client) -> tuple[dict, Path]:
        grid = directory / "grid.geojson"
        output = directory / "sr_hex.csv.gz"
        write_grid(grid)
        report = run_section2(
            client=client,
            policy_path=POLICY_PATH,
            grid_path=grid,
            output_path=output,
            supplemental_path=directory / "supplemental.geojson",
            report_path=directory / "report.json",
            logger=quiet_logger(),
        )
        return report, output

    def test_publishes_only_after_serialized_reference_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            report, output = self.run_pipeline(Path(directory_name), FakeS3Client())
            self.assertEqual(report["status"], "passed")
            self.assertTrue(report["reference_comparison"]["passed"])
            self.assertTrue(output.exists())
            self.assertIn("output_sha256", report)

    def test_reference_failure_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            output = directory / "sr_hex.csv.gz"
            output.write_bytes(b"previous-good-output")
            wrong_cell = h3.latlng_to_cell(-34.2, 18.8, 8)

            report, output = self.run_pipeline(directory, FakeS3Client(wrong_cell))

            self.assertEqual(report["status"], "failed")
            self.assertFalse(report["output_published"])
            self.assertEqual(output.read_bytes(), b"previous-good-output")
            self.assertIn("reference_validation_failed", report["failure_reasons"])


if __name__ == "__main__":
    unittest.main()
