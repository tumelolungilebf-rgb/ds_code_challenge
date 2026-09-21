"""Tests for the unified Sections 1-2 orchestration."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from yearbeyond_pipeline.full_pipeline import run_full_pipeline


def quiet_logger() -> logging.Logger:
    logger = logging.getLogger("yearbeyond.test.full")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


class FullPipelineTests(unittest.TestCase):
    def test_runs_sections_in_order_and_passes_one_client(self) -> None:
        client = object()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            with (
                patch(
                    "yearbeyond_pipeline.full_pipeline.run_section1",
                    return_value={"status": "passed", "run_id": "section-1"},
                ) as section1,
                patch(
                    "yearbeyond_pipeline.full_pipeline.run_section2",
                    return_value={"status": "passed", "run_id": "section-2"},
                ) as section2,
            ):
                summary = run_full_pipeline(root, quiet_logger(), client=client)

            self.assertEqual(summary["status"], "passed")
            self.assertEqual(summary["section1"]["run_id"], "section-1")
            self.assertEqual(summary["section2"]["run_id"], "section-2")
            self.assertIs(section1.call_args.kwargs["client"], client)
            self.assertIs(section2.call_args.kwargs["client"], client)
            saved = json.loads((root / "outputs" / "pipeline_summary.json").read_text())
            self.assertEqual(saved["status"], "passed")

    def test_section1_failure_skips_section2(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            with (
                patch(
                    "yearbeyond_pipeline.full_pipeline.run_section1",
                    return_value={"status": "failed", "run_id": "section-1"},
                ),
                patch("yearbeyond_pipeline.full_pipeline.run_section2") as section2,
            ):
                summary = run_full_pipeline(root, quiet_logger(), client=object())

            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["failure_stage"], "section1")
            self.assertEqual(summary["section2"]["status"], "skipped")
            section2.assert_not_called()

    def test_client_setup_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            with patch(
                "yearbeyond_pipeline.full_pipeline.create_s3_client",
                Mock(side_effect=RuntimeError("credentials unavailable")),
            ):
                summary = run_full_pipeline(root, quiet_logger())

            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["failure_stage"], "orchestration")
            self.assertEqual(summary["error"]["type"], "RuntimeError")
            self.assertTrue((root / "outputs" / "pipeline_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
