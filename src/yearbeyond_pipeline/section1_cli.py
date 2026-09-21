"""Command-line entry point for the standalone Section 1 pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .pipeline import configure_logger, run_section1

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse paths while providing reproducible project-local defaults."""
    parser = argparse.ArgumentParser(
        description="Extract and validate Section 1 H3 resolution-8 GeoJSON."
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=PROJECT_ROOT / "config" / "h3_level8_schema.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "city-hex-polygons-8.geojson",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "section1_validation.json",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "pipeline.log",
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run Section 1 and return a shell-friendly status code."""
    args = parse_args(arguments)
    logger = configure_logger(args.log)
    report = run_section1(
        client=None,
        contract_path=args.contract,
        output_path=args.output,
        report_path=args.report,
        logger=logger,
    )
    return 0 if report["status"] == "passed" else 1
