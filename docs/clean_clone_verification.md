# Clean-clone verification

Date: 21 September 2026  
Operating system: Windows 11 / PowerShell  
Python: 3.12.14  
Tested commit: `4443bdb199db291eb893f6f22e5dedc32a37ebe6`

## Purpose

The public fork was cloned into a new directory and installed in a fresh
virtual environment. The documented pipeline command and test suite were
then run.

The clean clone initially contained no `.venv`, `data/processed`, or `outputs`
directory.

## Setup correction discovered by the check

The first attempt at `fe795bf` found that the documented `py -3.12` command
was unavailable in the test environment. Python 3.12.14 was installed but
absent from `PATH`. Commit `4443bdb` updated the README to explain the
available ways to select Python.

For this environment, the full path to its Python 3.12.14 executable was used
only to create the clean clone's `.venv`. All subsequent commands used the new
environment's `.venv\Scripts\python.exe`.

## Results

These are the initial clean-clone results. The later review passed 34 tests;
see [final technical review](final_review.md).

| Check | Result |
| --- | --- |
| Editable install from `pyproject.toml` | Passed |
| Unified pipeline | Passed |
| Section 1 | Passed in 3.841 seconds |
| Section 2 | Passed in 61.182 seconds |
| Total pipeline time | 65.552 seconds |
| Unit tests | 32 passed |
| Tracked changes created by the run | None |

Section 1 extracted 3,832 features, achieved a 100% schema score, and matched
all 3,832 reference features with zero mismatches. Its output SHA-256 was:

```text
83c8a05b4f9b3528892ee75968b01f4fd4986f4bfc0e1c06d2f382b8671e489b
```

Section 2 retained 941,634 rows and matched the serialized reference with zero
identity, H3, shared-field, or row-count mismatches. Its output SHA-256 was:

```text
2724a0eea1007a5e16fd0a8037a95ffedb76e94735d768b4d4a1fd51635fabd0
```

Both hashes match the earlier live runs. Generated files remained ignored,
and the run left no tracked changes.
