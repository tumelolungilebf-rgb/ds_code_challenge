"""Command-line entry point for the complete scoped pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .full_pipeline import run_full_pipeline
from .pipeline import configure_logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run and validate YearBeyond assessment Sections 1 and 2."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="Repository root containing config, data and outputs directories.",
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = parse_args(arguments)
    project_root = args.project_root.resolve()
    logger = configure_logger(project_root / "outputs" / "pipeline.log")
    summary = run_full_pipeline(project_root=project_root, logger=logger)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
