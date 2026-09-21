# AI assistance log

Scope: Sections 0, 1 and 2 of the assessment. This file accompanies the code
because the assessment requires a repository AI log, in addition to our
Airtable working tracker.

Entries below were reconstructed from the existing Airtable AI Usage Log and
the conversation on 21 September 2026. Requests labelled as summaries are
paraphrases, not verbatim prompt transcripts. Historical model labels are
copied as recorded; exact model versions were not independently verified.
Exact per-session token counts were not exposed or captured. They are marked
unavailable rather than guessed; recover them from a reliable usage export
before submission if one becomes available. This remains a limitation against
the README's request to include token counts.

## 18 September 2026 - initial review and work tracking

- Recorded model: ChatGPT - GPT-5.6 Sol.
- Request summary: Review the challenge against the YearBeyond request, identify
  the Section 0-2 scope, and plan the work in Airtable.
- Use: Initial scope, task sequence, and tracking base design.
- Corrections: None recorded at that stage.
- Tokens: Unavailable; not captured.

## 21 September 2026 - move to Codex

- Recorded tool: Codex; exact model not recorded.
- Request summary: Use Codex for implementation while keeping Airtable as the
  work tracker.
- Use: Established the development workflow.
- Corrections: None recorded for this transition.
- Tokens: Unavailable; this entry originally described intended work.

## 21 September 2026 - scope, repository and account setup

- Recorded model/tool: Codex / GPT-5; Airtable plugin (historical label).
- Request summary: Read the full README, inspect the repository, plan only
  Sections 0-2 before implementation, teach each step, and track the work.
- Use: Reviewed plan, local clone, public fork, Git remotes and repository-local
  commit identity. Other active project repositories were left untouched.
- **User correction:** The assistant initially treated the absent Airtable CLI
  as meaning Airtable was unavailable. Tumelo said, "you have a airtable plug in
  here though". The assistant then used the direct plugin and accessed the
  intended base. This is a user-led correction of the AI workflow.
- Tokens: Unavailable.

## 21 September 2026 - isolated Python environment

- Recorded model/tool: Codex / GPT-5; Airtable plugin (historical label).
- Request summary: Continue the next setup task, teach it step by step, and
  track progress in Airtable.
- Use: Python 3.12.14 environment, `.gitignore`, `.python-version`, and checks
  of environment isolation. Evidence: commit `c7f7ecc`.
- Assistant verification: An initial push did not update the remote and was
  recorded as pending. It was subsequently pushed successfully. The historical
  log attributed the initial failure to authentication; this review has not
  independently verified that diagnosis.
- Tokens: Unavailable.

## 21 September 2026 - AWS source access

- Recorded model/tool: Codex / GPT-5; Airtable plugin (historical label).
- Request summary: Continue Section 0 with explanations and tracking evidence.
- Use: `scripts/check_source_access.py`; object access checks; a successful
  S3 Select probe using supplied credentials. Evidence: commit `c4f6ed2`.
- Assistant corrections: Fixed a PowerShell Content-Length conversion and
  replaced a fragile inline Python command with a reusable script after quoting
  errors. These were assistant corrections, not claimed as user corrections.
- Tokens: Unavailable.

## 21 September 2026 - source inspection

- Recorded model: Codex - current model (non-Astra); precise version unrecorded.
- Request summary: Continue gradually, explain the work, inspect the sources,
  stay within Sections 0-2, and keep Airtable updated.
- Use: `scripts/inspect_sources.py` and `docs/source_data_profile.json`;
  evidence: commit `ccec3f8`.
- Assistant correction: Initial code assumed uppercase Latitude/Longitude,
  but the files use lowercase names. The assistant fixed the lookup and reran
  the scan. This was identified by the assistant, not by Tumelo.
- Review limitation: Matching total counts do not establish row-level or
  polygon-level equality; these comparisons remain implementation work.
- Tokens: Unavailable.

## 21 September 2026 - Astra design review

- Model/tool: GPT-6 Astra in Codex; Airtable plugin and official documentation.
- Prompt: "Go ahead." Context: proceed with the proposed Section 1 design
  checkpoint after source inspection, with explanations before implementation.
- Use: `config/h3_level8_schema.json`, `docs/section1_design.md`, and this log.
  Defined six equally weighted checks, a 99.5% score threshold, mandatory
  critical checks, and an independent per-feature reference comparison.
- Assistant review corrections: Qualified earlier claims about aggregate
  counts; documented the profiler's limited meaning of valid coordinate pairs
  and its sampled mixed-file types. Distinguished user corrections from
  assistant self-corrections. Created the required repository AI log from the
  six existing Airtable entries rather than implying Airtable alone suffices.
- Validation: Parsed the contract and checked its rule IDs, threshold arithmetic
  and configuration relationships. No extraction/validator implementation or
  live Section 1 correctness result is claimed by this design checkpoint.
- Tokens: Unavailable from the tool outputs for this session.

## 21 September 2026 - Section 1 implementation

- Model/tool: GPT-5.6 Sol High in Codex; Airtable plugin.
- Prompt: "Okay I have switched back to Sol high." Context: continue from the
  approved Astra design into Section 1 implementation and tests.
- Use: Added the installable package, streamed S3 Select event parser, six-check
  schema scorer, critical gates, keyed reference comparison, atomic publication,
  structured timing logs and focused tests. Ran the live pipeline twice and
  recorded deterministic output and verified results.
- Assistant corrections and review improvements: The initial Airtable activity
  write used an unavailable `Implementation` select option and was retried with
  the existing `Code` option. A Windows compile command passed a wildcard
  literally and was replaced with explicit file enumeration and test discovery.
  Credential creation was moved inside the measured pipeline so setup failures
  can produce evidence. These were assistant corrections, not user corrections.
- Validation: 20 tests passed. Both live runs extracted 3,832 features, scored
  100%, matched the reference with zero differences and produced the same
  SHA-256 output hash.
- Tokens: Unavailable from the Codex interface; not estimated.

## 21 September 2026 - Section 2 evidence and Astra design review

- Model/tool: GPT-6 Astra in Codex; Airtable plugin and official H3 documentation.
- Prompts: "on to the next task." and "I have switched to Astra."
- Use: Added `scripts/inspect_section2.py`, its aggregate report
  `docs/section2_probe.json`, `config/section2_policy.json`, and
  `docs/section2_design.md`. Streamed all 941,634 source/reference rows and
  compared all 15 shared fields, row identity, calculated H3 indices and grid
  membership. Confirmed source notification uniqueness and the unnamed export
  index sequence. Compared all 3,832 grid boundaries with the H3 library.
- Finding and assistant correction: A candidate strict grid lookup would
  produce three reference mismatches. The measured evidence showed three
  requests belong to two valid H3 cells missing from the supplied grid.
  The design was revised to retain calculated indices through a documented
  supplemental-cell fallback, keep original failure counts visible, and enforce
  explicit total/unexpected failure thresholds plus exact reference agreement.
  This was an assistant-led investigation, not a user correction.
- Validation: Synthetic checks covered seven coordinate cases and four boundary
  comparisons. The full scan and follow-up coverage-gap scan both found zero
  direct H3/reference mismatches, zero shared-field mismatches and three grid
  membership gaps. The policy JSON and boundary arithmetic were checked locally.
  Production Section 2 transformation and regression tests remain pending.
- Tokens: Exact session count unavailable; not estimated.
