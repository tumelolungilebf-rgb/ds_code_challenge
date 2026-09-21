"""Orchestrate the complete Section 1 extraction and validation run."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from .extract import LEVEL_8_SELECT_SQL, extract_level8_features
from .sources import (
    BUCKET,
    LEVEL_8_REFERENCE_OBJECT,
    MIXED_RESOLUTION_OBJECT,
    REGION,
    create_s3_client,
    get_object_metadata,
    read_json_object,
)
from .validate import compare_with_reference, load_contract, validate_collection


def utc_now() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC).isoformat()


def atomic_write_json(path: Path, payload: Any, compact: bool = False) -> None:
    """Write JSON in the target directory and atomically replace the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            if compact:
                json.dump(payload, temporary, sort_keys=True, separators=(",", ":"))
            else:
                json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def configure_logger(log_path: Path) -> logging.Logger:
    """Log compact JSON events to both the console and a local file."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("yearbeyond.section1")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(message)s")
    for handler in (
        logging.StreamHandler(),
        logging.FileHandler(log_path, encoding="utf-8"),
    ):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, event: str, **details: Any) -> None:
    """Write one structured log event without credential values."""
    logger.info(
        json.dumps(
            {"timestamp_utc": utc_now(), "event": event, **details},
            sort_keys=True,
            default=str,
        )
    )


def _timed_call(
    timings: dict[str, float], stage: str, function: Any, *args: Any
) -> Any:
    """Execute a function and record monotonic elapsed seconds for its stage."""
    started = perf_counter()
    try:
        return function(*args)
    finally:
        timings[stage] = round(perf_counter() - started, 6)


def _sources_unchanged(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]
) -> bool:
    """Return whether all captured source metadata stayed identical."""
    return before == after


def run_section1(
    client: Any | None,
    contract_path: Path,
    output_path: Path,
    report_path: Path,
    logger: logging.Logger,
) -> dict[str, Any]:
    """Extract, validate, compare, publish on success, and always write a report."""
    run_id = str(uuid4())
    total_started = perf_counter()
    timings: dict[str, float] = {}
    report: dict[str, Any] = {
        "run_id": run_id,
        "started_at_utc": utc_now(),
        "status": "failed",
        "bucket": BUCKET,
        "region": REGION,
        "query": LEVEL_8_SELECT_SQL,
        "contract_path": str(contract_path),
        "output_path": str(output_path),
        "output_published": False,
        "output_existed_before_run": output_path.exists(),
    }
    log_event(logger, "section1_started", run_id=run_id)

    try:
        contract = _timed_call(timings, "load_contract", load_contract, contract_path)
        if client is None:
            client = _timed_call(
                timings, "credential_and_client_setup", create_s3_client
            )
        metadata_before = {
            object_key: _timed_call(
                timings,
                f"head_before:{object_key}",
                get_object_metadata,
                client,
                object_key,
            )
            for object_key in (MIXED_RESOLUTION_OBJECT, LEVEL_8_REFERENCE_OBJECT)
        }
        report["source_metadata_before"] = metadata_before

        extraction = _timed_call(
            timings, "s3_select_extraction", extract_level8_features, client
        )
        collection = extraction.as_feature_collection()
        report["s3_select_statistics"] = extraction.statistics
        report["extracted_feature_count"] = len(extraction.features)
        log_event(
            logger,
            "s3_select_completed",
            run_id=run_id,
            feature_count=len(extraction.features),
            statistics=extraction.statistics,
            elapsed_seconds=timings["s3_select_extraction"],
        )

        reference = _timed_call(
            timings,
            "reference_download",
            read_json_object,
            client,
            LEVEL_8_REFERENCE_OBJECT,
        )
        schema_validation = _timed_call(
            timings, "schema_validation", validate_collection, collection, contract
        )
        reference_comparison = _timed_call(
            timings,
            "reference_comparison",
            compare_with_reference,
            collection,
            reference,
            contract,
        )
        report["schema_validation"] = schema_validation
        report["reference_comparison"] = reference_comparison
        log_event(
            logger,
            "validation_completed",
            run_id=run_id,
            score_percent=schema_validation["score_percent"],
            schema_passed=schema_validation["passed"],
            reference_passed=reference_comparison["passed"],
            schema_elapsed_seconds=timings["schema_validation"],
            reference_elapsed_seconds=timings["reference_comparison"],
        )

        metadata_after = {
            object_key: _timed_call(
                timings,
                f"head_after:{object_key}",
                get_object_metadata,
                client,
                object_key,
            )
            for object_key in (MIXED_RESOLUTION_OBJECT, LEVEL_8_REFERENCE_OBJECT)
        }
        report["source_metadata_after"] = metadata_after
        report["sources_unchanged_during_run"] = _sources_unchanged(
            metadata_before, metadata_after
        )

        accepted = (
            schema_validation["passed"]
            and reference_comparison["passed"]
            and report["sources_unchanged_during_run"]
        )
        if accepted:
            collection["features"].sort(
                key=lambda feature: feature["properties"]["index"]
            )
            _timed_call(
                timings, "output_write", atomic_write_json, output_path, collection, True
            )
            report["status"] = "passed"
            report["output_published"] = True
            log_event(
                logger,
                "output_published",
                run_id=run_id,
                path=str(output_path),
                feature_count=len(collection["features"]),
            )
        else:
            failure_reasons = []
            if not schema_validation["passed"]:
                failure_reasons.append("schema_validation_failed")
            if not reference_comparison["passed"]:
                failure_reasons.append("reference_comparison_failed")
            if not report["sources_unchanged_during_run"]:
                failure_reasons.append("source_changed_during_run")
            report["failure_reasons"] = failure_reasons
    except Exception as error:
        report["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
        log_event(
            logger,
            "section1_error",
            run_id=run_id,
            error_type=type(error).__name__,
            message=str(error),
        )

    report["finished_at_utc"] = utc_now()
    timings["total"] = round(perf_counter() - total_started, 6)
    report["timings_seconds"] = timings
    atomic_write_json(report_path, report)
    log_event(
        logger,
        "section1_finished",
        run_id=run_id,
        status=report["status"],
        output_published=report["output_published"],
        elapsed_seconds=timings["total"],
        report_path=str(report_path),
    )
    return report
