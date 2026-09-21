# Final technical review

Reviewed on 21 September 2026 against the original upstream README at
`48907f239ff96270c0bea9c796f84a4414180e6d` and the YearBeyond application brief.
Only Sections 0, 1 and 2 are included. The application brief asks for roughly
8 hours of work and a public fork link by 22 September, 23:59 SAST.

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
| AI disclosure | `AI_log.md` includes requests, models, extensive-use summary and actual user corrections |

## Findings corrected

1. Restored the clean-clone AI-log entry removed in `db5e7f8`, retaining the
   newer audit entry and the user's model-label and README edits.
2. Added explicit CSV header and row-width checks. The comparator previously
   ignored extra unnamed values after the expected columns; duplicate headers
   could also hide values. Two regression tests failed before the fix and pass
   after it. Errors identify the side and row position without logging content.
3. Clarified historical design/result checkpoints and README timings. Explained
   that individual file replacement is not a multi-file transaction; readers
   must check the latest summary and stage reports for success.

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

The audit scanned 153 historical Git blobs with targeted credential-pattern
checks and found no matches. This is a bounded scan, not a proof that every
possible secret format is detectable. No generated datasets or environments
are tracked. All relative Markdown links resolved at review.

## Practical limits and handoff

Verification used Windows and Python 3.12.14. POSIX setup commands are provided
but have not been independently executed on Linux or macOS. Direct runtime
dependencies are pinned; transitive and build dependencies are not fully locked.
The public S3 service and inputs remain external dependencies. Metadata checks
detect changes during a run, not permanent preservation of a source version.

The supplied H3 grid has two missing cells used by three requests. This is
handled and audited explicitly, rather than hidden by changing the original
grid. The join method is specific to this verified H3 grid, not a general
solution for arbitrary polygons. Identity uniqueness checks use memory
proportional to the number of requests, although CSV rows are streamed.

Exact AI token counts were not captured. The log describes usage honestly and
provides the rough-use account requested by the application brief; it cannot
supply the exact counts requested by the generic challenge.

The scoped technical work passes this review. Submission still requires the
candidate to reply to the invitation email with the public fork link. This
review does not send that email or establish the candidate's interview readiness.
