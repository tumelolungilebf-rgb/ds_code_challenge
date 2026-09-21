# Section 2 transformation results

Status: production transformation completed and validated on 21 September 2026.

## Command

After Section 1 has produced the validated resolution-8 grid, run:

```powershell
.venv\Scripts\python.exe -m yearbeyond_pipeline.section2_cli
```

The generated dataset and run artifacts are intentionally ignored by Git:

- `data/processed/sr_hex.csv.gz`
- `outputs/section2_validation.json`
- `outputs/section2_supplemental_cells.geojson`
- `outputs/pipeline.log`

## Full-data result

The pipeline streamed all 941,634 source rows and retained their original order
and 15 named source fields. It appended `h3_level8_index` and omitted the unnamed
CSV export column only after verifying that every value was the expected
zero-based row number.

| Check | Result |
| --- | ---: |
| Source rows | 941,634 |
| Unique nonempty notification numbers | 941,634 |
| Missing both coordinates, assigned `0` | 212,364 |
| Missing only one coordinate | 0 |
| Nonnumeric, nonfinite or out-of-range coordinates | 0 |
| Usable coordinate pairs | 729,270 |
| Assigned within the original grid | 729,267 |
| Outside the original grid and recovered | 3 |
| Original-grid unjoined rows | 212,367 |
| Unexpected join errors | 3 |
| Reference row identity mismatches | 0 |
| Reference H3 mismatches | 0 |
| Reference shared-field mismatch rows | 0 |
| Reference unpaired rows | 0 |

The original-grid unjoined rate was 22.553030%, below the configured 25%
maximum. This rate includes expected missing locations so that missingness stays
visible. The unexpected join error rate was 0.000411%, below the 0.001% maximum.
The three unexpected rows were recovered using two H3 cells derived from their
coordinates. They remain counted as original-grid failures in the report.

The derived cells are stored separately with the provenance
`h3_derived_coverage_gap`. The successful Section 1 grid is not modified.

## Reference and reproducibility evidence

Validation reopened the serialized candidate gzip and compared every field of
every row with `sr_hex.csv.gz`. All 941,634 rows matched. The source object
metadata was also identical before and after each run.

Two complete live runs produced the same output SHA-256:

`2724a0eea1007a5e16fd0a8037a95ffedb76e94735d768b4d4a1fd51635fabd0`

| Run | Transform | Serialized validation | Total |
| --- | ---: | ---: | ---: |
| 1 | 56.849 s | 26.449 s | 85.420 s |
| 2 | 57.723 s | 25.086 s | 86.592 s |

The second run is the current local report. Its run ID is
`159fc701-e444-4e72-a258-d3091742e7d0`.

## Test evidence

All 29 repository tests passed. Section 2 tests cover coordinate categories,
row preservation, missing-coordinate assignment, dynamically derived grid
coverage, deterministic gzip output, invalid coordinates, the unnamed-column
guard, the exact error threshold boundary, reordered reference rows, and safe
publication. The publication test proves that a failed reference comparison
does not replace an existing successful output.

Interview explanation: the join key is calculated from each latitude and
longitude with the pinned H3 library. A left-join policy retains every request.
Missing locations receive `0`; malformed coordinates fail the run. Valid cells
missing from the supplied grid are derived from the H3 definition, recorded as
coverage failures, and audited separately. The produced file is only published
after its serialized contents match the supplied reference exactly.
