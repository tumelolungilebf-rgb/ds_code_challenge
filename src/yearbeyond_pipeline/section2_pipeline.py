"""Orchestrate safe publication of the Section 2 transformed dataset."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import h3

from .pipeline import atomic_write_json, log_event, utc_now
from .sources import (
    BUCKET,
    REGION,
    SERVICE_REQUEST_OBJECT,
    SERVICE_REQUEST_REFERENCE_OBJECT,
    create_s3_client,
    get_object_metadata,
)
from .transform import (
    compare_csv_with_reference,
    load_grid,
    load_policy,
    open_local_gzip_csv,
    open_s3_gzip_csv,
    sha256_file,
    transform_csv,
)


def run_section2(
    client: Any | None,
    policy_path: Path,
    grid_path: Path,
    output_path: Path,
    supplemental_path: Path,
    report_path: Path,
    logger: Any,
) -> dict[str, Any]:
    """Transform, validate, and publish Section 2 artifacts only on success."""
    run_id = str(uuid4())
    started = perf_counter()
    timings: dict[str, float] = {}
    temporary_output: Path | None = None
    temporary_supplemental: Path | None = None
    report: dict[str, Any] = {
        "run_id": run_id,
        "started_at_utc": utc_now(),
        "status": "failed",
        "bucket": BUCKET,
        "region": REGION,
        "policy_path": str(policy_path),
        "grid_path": str(grid_path),
        "output_path": str(output_path),
        "supplemental_path": str(supplemental_path),
        "output_published": False,
        "output_existed_before_run": output_path.exists(),
    }
    log_event(logger, "section2_started", run_id=run_id)

    try:
        stage = perf_counter()
        policy = load_policy(policy_path)
        allowed_cells, grid_hash = load_grid(grid_path, policy["resolution"])
        timings["configuration_and_grid_validation"] = round(perf_counter() - stage, 6)
        report["grid_sha256"] = grid_hash
        report["grid_cell_count"] = len(allowed_cells)
        report["h3_versions"] = h3.versions()

        if client is None:
            stage = perf_counter()
            client = create_s3_client()
            timings["credential_and_client_setup"] = round(perf_counter() - stage, 6)

        object_keys = (SERVICE_REQUEST_OBJECT, SERVICE_REQUEST_REFERENCE_OBJECT)
        stage = perf_counter()
        before = {key: get_object_metadata(client, key) for key in object_keys}
        timings["source_metadata_before"] = round(perf_counter() - stage, 6)
        report["source_metadata_before"] = before

        output_path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        )
        temporary_output = Path(handle.name)
        handle.close()

        stage = perf_counter()
        with open_s3_gzip_csv(client, SERVICE_REQUEST_OBJECT) as source:
            transformation = transform_csv(source, temporary_output, allowed_cells, policy)
        timings["streaming_transformation"] = round(perf_counter() - stage, 6)
        report["transformation"] = {
            key: value
            for key, value in transformation.items()
            if key != "supplemental_grid"
        }
        log_event(
            logger,
            "section2_transformation_completed",
            run_id=run_id,
            elapsed_seconds=timings["streaming_transformation"],
            counts=transformation["counts"],
            rates=transformation["rates"],
            failure_reasons=transformation["failure_reasons"],
        )

        reference_comparison = {"passed": False, "skipped": True}
        if not transformation["failure_reasons"]:
            stage = perf_counter()
            with open_local_gzip_csv(temporary_output) as candidate:
                with open_s3_gzip_csv(client, SERVICE_REQUEST_REFERENCE_OBJECT) as reference:
                    reference_comparison = compare_csv_with_reference(
                        csv.DictReader(candidate), reference, policy
                    )
            timings["serialized_reference_validation"] = round(
                perf_counter() - stage, 6
            )
        report["reference_comparison"] = reference_comparison

        stage = perf_counter()
        after = {key: get_object_metadata(client, key) for key in object_keys}
        timings["source_metadata_after"] = round(perf_counter() - stage, 6)
        report["source_metadata_after"] = after
        report["sources_unchanged_during_run"] = before == after

        failure_reasons = list(transformation["failure_reasons"])
        if not reference_comparison.get("passed"):
            failure_reasons.append("reference_validation_failed")
        if not report["sources_unchanged_during_run"]:
            failure_reasons.append("source_changed_during_run")
        report["failure_reasons"] = failure_reasons

        if not failure_reasons:
            supplemental_path.parent.mkdir(parents=True, exist_ok=True)
            supplement_handle = tempfile.NamedTemporaryFile(
                dir=supplemental_path.parent,
                prefix=f".{supplemental_path.name}.",
                suffix=".tmp",
                delete=False,
            )
            temporary_supplemental = Path(supplement_handle.name)
            supplement_handle.close()
            atomic_write_json(
                temporary_supplemental, transformation["supplemental_grid"], compact=True
            )
            stage = perf_counter()
            report["output_sha256"] = sha256_file(temporary_output)
            report["supplemental_sha256"] = sha256_file(temporary_supplemental)
            os.replace(temporary_supplemental, supplemental_path)
            temporary_supplemental = None
            os.replace(temporary_output, output_path)
            temporary_output = None
            timings["publication"] = round(perf_counter() - stage, 6)
            report["status"] = "passed"
            report["output_published"] = True
            log_event(
                logger,
                "section2_output_published",
                run_id=run_id,
                output_sha256=report["output_sha256"],
                source_rows=transformation["counts"]["source_rows"],
            )
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        log_event(
            logger,
            "section2_error",
            run_id=run_id,
            error_type=type(error).__name__,
            message=str(error),
        )
    finally:
        for path in (temporary_output, temporary_supplemental):
            if path is not None:
                path.unlink(missing_ok=True)

    report["finished_at_utc"] = utc_now()
    timings["total"] = round(perf_counter() - started, 6)
    report["timings_seconds"] = timings
    atomic_write_json(report_path, report)
    log_event(
        logger,
        "section2_finished",
        run_id=run_id,
        status=report["status"],
        output_published=report["output_published"],
        elapsed_seconds=timings["total"],
    )
    return report
