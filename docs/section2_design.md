# Section 2: measured join design

Design and source inspection recorded on 21 September 2026, before
implementation. Results are in [Section 2 results](section2_results.md) and
the [final review](final_review.md).

## Requirement

Assign each service request to one resolution-8 H3 cell using the equivalent
of the supplied grid. Assign index `0` when coordinates are empty, validate
against `sr_hex.csv.gz`, log join failures and operation timings, and fail above
a documented join error threshold. The method and thresholds are project
design choices, explained below.

## Evidence collected before deciding

`scripts/inspect_section2.py` streamed `sr.csv.gz` and `sr_hex.csv.gz` together,
compared every shared field as text, calculated candidate H3 indices from source
coordinates, and checked membership in the validated Section 1 grid. The
aggregate report is `docs/section2_probe.json`. It excludes individual request
records and notification identifiers.

| Check | Observed result |
| --- | ---: |
| Source and reference rows | 941,634 each |
| Distinct nonempty source notification numbers | 941,634 |
| Row identity, shared value or length mismatches | 0 |
| Rows missing both coordinates | 212,364 |
| Rows missing only one coordinate | 0 |
| Nonnumeric, nonfinite or out-of-range coordinate pairs | 0 |
| Usable coordinate pairs | 729,270 |
| Usable pairs whose calculated cell is in the supplied grid | 729,267 |
| Usable pairs whose calculated cell is absent from that grid | 3 |
| Calculated H3 indices differing from reference | 0 |
| Missing-location rows whose reference index is nonzero | 0 |
| Reference nonzero indices absent from the supplied grid | 3 |
| Distinct calculated cells | 2,082 |

All 3,832 supplied grid polygons have the same vertices as H3 4.5.0 boundaries
within 1e-9 degrees, allowing cyclic ring ordering and reversal. This supports
H3 addressing for this grid. Matching vertices alone does not establish that
planar and spherical edges are identical.

The three exceptional requests occupy two cells:

| Missing cell | Request count | Adjacent supplied cells |
| --- | ---: | ---: |
| `88ad361b51fffff` | 1 | 3 |
| `88ad36c629fffff` | 2 | 3 |

The supplied cell set has two coverage gaps. The reason for their omission is
unknown. Assigning `0` to these requests would produce three reference
mismatches. The pipeline must discover missing cells from the input data,
without hard-coding the observed IDs.

The unnamed source CSV column equals the complete sequence 0 through 941,633.
The output can omit this verified export index while preserving every named
field and row. The same sequence check must pass on subsequent runs.

## Selected method

Use a left join on a calculated H3 key. A left join retains every source row
even if no cell is found. For each row:

1. Resolve the actual lowercase coordinate headers, rejecting duplicate or
   ambiguous headers. Preserve identifiers, timestamps and other fields as text.
2. If either coordinate is blank after trimming, retain the row with index `0`.
   Count missing-both and missing-one separately. Handling one missing coordinate
   the same way extends the README's empty-field rule.
3. Parse nonempty coordinates, require finite values and latitude in [-90, 90]
   and longitude in [-180, 180]. Count invalid categories and fail the run for
   any such malformed values; no output is published from that run.
4. Compute `h3.latlng_to_cell(latitude, longitude, 8)` and look up that key in
   the validated grid. Each grid index must be unique, preventing one request
   from multiplying into multiple output rows.
5. For an absent cell, record the original join failure. Derive the cell's
   geometry using the same H3 library and record it in a separate supplemental
   FeatureCollection. Join the request to that derived cell and retain the
   calculated index, subject to the error thresholds below.

Tag each derived cell with `source: h3_derived_coverage_gap`. Record the H3
library version and recovered request count. Convert the library's
latitude/longitude pairs to GeoJSON longitude/latitude and close the ring.
Save these cells separately, leaving the Section 1 grid unchanged.

The [official H3 Python API](https://uber.github.io/h3-py/api_quick.html)
documents coordinate-to-cell and cell-to-boundary operations. That API uses
latitude/longitude; GeoJSON positions use longitude/latitude. At cell edges,
use the pinned library's assignment and test its boundary behaviour.

The selected method uses the verified H3 indices and boundaries. Direct
calculation matched every reference assignment in the probe and avoids an
additional GIS dependency. Grid membership, failed matches and derived cells
are checked separately. Arbitrary or clipped polygons would require a spatial
join with rules for boundary points and multiple matches.

## Error thresholds and rationale

The standalone configuration is `config/section2_policy.json`. Fractions in
that file are in [0, 1], not percentages. Never compare display-rounded rates.

Define N as all rows, M as rows with either coordinate missing, I as rows with
nonempty but invalid coordinates, and G as usable rows outside the original
grid. E = N - M is the nonmissing-coordinate denominator.

| Policy | Formula | Maximum | Observed |
| --- | --- | --- | --- |
| Original-grid unjoined rate | Sum of M, I and G, divided by N | 25% | 22.553030% |
| Unexpected join error rate | Sum of I and G, divided by E | 0.001% | 0.000411% |

Stop if either rate exceeds its maximum. Empty inputs, E = 0 and invalid
coordinates also fail the run.

The 25% cap allows for the observed 22.552712% missing-location rate with
limited headroom. It provides an operational check for a substantial increase
in missing data or a broken column mapping. Report missing locations even
when the run is below the limit.

The 0.001% cap permits at most seven unexpected gaps among 729,270 eligible
rows; eight would fail. The observed three gaps fit within this small tolerance.
The tolerance allows a small number of source coverage gaps. It was selected
after inspection and should be reviewed if the source changes. Record the
reason for any future threshold change.

Count G before recovery. Report both the original failure rate and recovered
count. Reference validation must find zero H3 mismatches, regardless of the
join error rates.

## Reference validation and row preservation

The exploratory scan established that source and reference are aligned and
have unique notification numbers. The production run may compare streams in
that order, but must check the identity and every shared source field at every
position and detect extra or missing rows using a full-length comparison.
An order change must fail validation. Supporting reordered input would require
a keyed lookup or external sort.

Keep all 15 named fields in source order and append `h3_level8_index`. Omit
only the verified unnamed export index. Preserve text values and row order.
Duplicate notification identities fail validation. Keep identifier strings
and coordinate precision unchanged.

Calculate assignments from source coordinates and grid membership. Use the
reference only for validation. Reopen the temporary output and compare its
contents before publication so validation also covers serialization errors.

## Implementation and verification handoff

Add a transformation module and focused tests, reusing shared S3 access and
logging. Provide one documented command for the combined Sections 1-2 run.
On a new checkout, the normal path must obtain and validate Section 1 output
automatically. A standalone Section 2 run requires the validated local grid
from Section 1.

Stream the compressed CSVs and output. Keep the small grid and a set of
notification identifiers in memory. The identifier set grows with the number
of requests; row dictionaries are processed one at a time. Derive each
missing cell once.

Write transformed data to a temporary gzip file, with fixed gzip timestamp
and filename metadata for deterministic bytes. Validate that file, then publish
`data/processed/sr_hex.csv.gz`. Write the supplemental grid under `outputs/`
and include checksums and a shared run ID in `outputs/section2_validation.json`.
Stage the files and publish a success report last. Replacement is atomic per
file, so an interruption can leave outputs from different runs. Consumers must
check the latest run summary before using them.

Log UTC timestamps, status, source metadata before/after, Python/H3 versions,
input/output counts, missing/invalid/covered/recovered categories, both error
rates and thresholds, reference differences, output checksums and per-stage
monotonic timings. Restrict logs to aggregate diagnostics and bounded cell-level
examples, without resident records or credential values.

Tests should include known coordinate-to-cell mapping, reversed coordinates,
missing one/both coordinates, malformed/NaN/infinite/out-of-range values,
duplicate grid and notification IDs, wrong H3 resolution, empty/all-missing
input, an uncovered cell and supplemental provenance, boundary assignment,
exact threshold limits and one row above, missing/extra/reordered reference
rows, equal counts with incorrect identities, altered shared values, output
serialization corruption, deterministic gzip, and failure before publication.
Use small synthetic examples for failure tests and the full supplied reference
for final validation. Use independent expected assignments where possible.

The probe covered coordinate categories and boundary comparisons. Production
tests and clean-clone results are recorded in the linked results and final
review documents.
