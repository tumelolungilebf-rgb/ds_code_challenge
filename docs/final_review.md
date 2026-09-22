# Final technical review

Reviewed on 21 September 2026 against the original upstream README at
`48907f239ff96270c0bea9c796f84a4414180e6d` and the YearBeyond application brief.
Scope: Sections 0, 1 and 2.

## Requirement checks

| Requirement | Evidence |
| --- | --- |
| Public fork, meaningful commits, upstream checked | GitHub API confirms public fork of `cityofcapetown/ds_code_challenge`; upstream remains `48907f2` |
| Reproducible setup and automatic source access | README, `pyproject.toml`, fresh Python 3.12.14 environment and complete run |
| S3 Select resolution-8 extraction | `extract.py`, live 3,832-feature result |
| Standalone schema and non-binary score | `config/h3_level8_schema.json`, six checks, 99.5% threshold, critical gates |
| Section 1 independent reference validation | 100% schema score and zero feature mismatches |
| H3 assignment and missing locations | Coordinate-derived H3 keys checked against grid; missing coordinates assigned `0` |
| Join failures, justified thresholds and timing | `config/section2_policy.json`, aggregate counts, two rate gates and measured stage timings |
| Section 2 independent reference validation | 941,634 serialized rows; zero field, identity, H3 or row-count mismatches |
| Tests and maintainable modules | 34 tests; extraction, validation, transformation and orchestration separated |
| AI disclosure | `AI_log.md` records requests, models, work produced and corrections |

## Findings corrected

1. Added CSV header and row-width checks. The comparator previously
   ignored extra unnamed values after the expected columns; duplicate headers
   could also hide values. Two regression tests failed before the fix and pass
   after it. Errors identify the side and row position without logging content.
2. Labelled earlier design and result checkpoints and updated README timings.
   Documented file-by-file publication and the need to check the latest run
   summary before using an output.
3. Restored a missing clean-clone entry in the AI log while preserving the
   later audit and user edits.

## Verification after the code correction

Tested public commit: `185b76e1ddd76dd6e3ca1590ef05d9a4a71ea2ba`.
Cloned into a new directory, created a new Python 3.12.14 environment, and ran
the documented editable install, pipeline and test commands. Python's full
executable path was used for environment creation, as allowed by the README.

- Installation and `pip check`: passed.
- Tests: 34 passed.
- Section 1: passed in 4.138 seconds; 3,832 features; score 100%.
- Section 2: passed in 62.070 seconds; 941,634 rows; zero reference mismatches.
- Combined: passed in 66.779 seconds, run ID
  `9d4c1e90-2af1-40ee-96e9-83e71c1ef671`.
- Both output hashes match [the initial clean-clone evidence](clean_clone_verification.md).
- Source metadata remained stable; the run created no tracked changes.

The audit checked 153 historical Git blobs for selected credential patterns
and found no matches. The scan covers those patterns only. Generated datasets
and environments are excluded from Git. All relative Markdown links resolved.

## Operating limits

Verification used Windows and Python 3.12.14. POSIX setup commands are provided
but have not been independently executed on Linux or macOS. Direct runtime
dependencies are pinned; transitive and build dependencies are not fully locked.
The public S3 service and inputs remain external dependencies. Metadata checks
detect changes during a run, not permanent preservation of a source version.

Two cells absent from the supplied grid are derived and saved separately for
the three affected requests. The assignment method relies on this dataset's
H3 grid structure. Arbitrary polygons would require a different join method.
CSV rows are streamed, but the set used to check identity uniqueness grows
with the number of requests.

The reviewed implementation passed the checks above. AI usage details and
token-count availability are recorded in [AI_log.md](../AI_log.md).
