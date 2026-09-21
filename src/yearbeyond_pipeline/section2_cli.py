"""Command-line entry point for the Section 2 transformation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .pipeline import configure_logger
from .section2_pipeline import run_section2

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assign service requests to H3 resolution-8 cells and validate them."
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=PROJECT_ROOT / "config" / "section2_policy.json",
    )
    parser.add_argument(
        "--grid",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "city-hex-polygons-8.geojson",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "sr_hex.csv.gz",
    )
    parser.add_argument(
        "--supplemental",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "section2_supplemental_cells.geojson",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "section2_validation.json",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "pipeline.log",
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = parse_args(arguments)
    logger = configure_logger(args.log)
    report = run_section2(
        client=None,
        policy_path=args.policy,
        grid_path=args.grid,
        output_path=args.output,
        supplemental_path=args.supplemental,
        report_path=args.report,
        logger=logger,
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
