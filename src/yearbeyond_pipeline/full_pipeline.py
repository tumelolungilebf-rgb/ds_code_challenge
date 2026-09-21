"""Run the scoped Sections 1 and 2 as one reproducible pipeline."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from .pipeline import atomic_write_json, log_event, run_section1, utc_now
from .section2_pipeline import run_section2
from .sources import create_s3_client


def run_full_pipeline(
    project_root: Path,
    logger: Any,
    summary_path: Path | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Run Section 1 then Section 2, stopping if their dependency fails."""
    run_id = str(uuid4())
    started = perf_counter()
    if summary_path is None:
        summary_path = project_root / "outputs" / "pipeline_summary.json"
    summary: dict[str, Any] = {
        "run_id": run_id,
        "started_at_utc": utc_now(),
        "status": "failed",
        "scope": ["Section 1", "Section 2"],
        "section1": {"status": "not_run"},
        "section2": {"status": "not_run"},
    }
    log_event(logger, "full_pipeline_started", run_id=run_id)

    try:
        stage = perf_counter()
        if client is None:
            client = create_s3_client()
        summary["client_setup_seconds"] = round(perf_counter() - stage, 6)

        section1_report_path = project_root / "outputs" / "section1_validation.json"
        section1_report = run_section1(
            client=client,
            contract_path=project_root / "config" / "h3_level8_schema.json",
            output_path=(
                project_root / "data" / "processed" / "city-hex-polygons-8.geojson"
            ),
            report_path=section1_report_path,
            logger=logger,
        )
        summary["section1"] = {
            "status": section1_report["status"],
            "report_path": str(section1_report_path),
            "run_id": section1_report.get("run_id"),
        }

        if section1_report["status"] != "passed":
            summary["section2"] = {
                "status": "skipped",
                "reason": "Section 1 did not pass",
            }
            summary["failure_stage"] = "section1"
        else:
            section2_report_path = project_root / "outputs" / "section2_validation.json"
            section2_report = run_section2(
                client=client,
                policy_path=project_root / "config" / "section2_policy.json",
                grid_path=(
                    project_root
                    / "data"
                    / "processed"
                    / "city-hex-polygons-8.geojson"
                ),
                output_path=project_root / "data" / "processed" / "sr_hex.csv.gz",
                supplemental_path=(
                    project_root
                    / "outputs"
                    / "section2_supplemental_cells.geojson"
                ),
                report_path=section2_report_path,
                logger=logger,
            )
            summary["section2"] = {
                "status": section2_report["status"],
                "report_path": str(section2_report_path),
                "run_id": section2_report.get("run_id"),
            }
            if section2_report["status"] == "passed":
                summary["status"] = "passed"
            else:
                summary["failure_stage"] = "section2"
    except Exception as error:
        summary["failure_stage"] = "orchestration"
        summary["error"] = {"type": type(error).__name__, "message": str(error)}
        log_event(
            logger,
            "full_pipeline_error",
            run_id=run_id,
            error_type=type(error).__name__,
            message=str(error),
        )

    summary["finished_at_utc"] = utc_now()
    summary["total_seconds"] = round(perf_counter() - started, 6)
    atomic_write_json(summary_path, summary)
    log_event(
        logger,
        "full_pipeline_finished",
        run_id=run_id,
        status=summary["status"],
        section1_status=summary["section1"]["status"],
        section2_status=summary["section2"]["status"],
        total_seconds=summary["total_seconds"],
        summary_path=str(summary_path),
    )
    return summary
