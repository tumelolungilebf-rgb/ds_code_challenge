# Section 2: measured join design

Historical design and exploratory checkpoint, 21 September 2026. Future-tense
statements below describe the plan before implementation. Production work is
now complete; see [verified results](section2_results.md) and the
[final review](final_review.md). Scope remains Sections 0-2.

## Requirement

Assign each service request to one resolution-8 H3 cell using the equivalent
of the supplied grid. Assign index `0` when coordinates are empty, validate
against `sr_hex.csv.gz`, log join failures and operation timings, and fail above
a documented join error threshold. The README does not prescribe a specific
join algorithm or numeric threshold; those choices are explained below.

## Evidence collected before deciding

`scripts/inspect_section2.py` streamed `sr.csv.gz` and `sr_hex.csv.gz` together,
compared every shared field as text, calculated candidate H3 indices from source
coordinates, and checked membership in the validated Section 1 grid. The
aggregate report is `docs/section2_probe.json`; no service-request records or
notification identifiers are included in it.

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
using H3 addressing for this regular grid. It is not a claim that all arbitrary
polygons can be joined this way or that planar and spherical edges are identical.

The three exceptional requests occupy two cells:

| Missing cell | Request count | Adjacent supplied cells |
| --- | ---: | ---: |
| `88ad361b51fffff` | 1 | 3 |
| `88ad36c629fffff` | 2 | 3 |

These are coverage gaps in the supplied cell set. Adjacency is consistent with
an edge-of-grid gap, but does not establish why the source grid omitted them.
A strict join returning `0` for these rows would create three reference
mismatches. The missing cell IDs are diagnostic observations; the implementation
must discover gaps dynamically and must not special-case these IDs.

The unnamed source CSV column equals the complete sequence 0 through 941,633.
It is therefore safe for this input to omit that verified export index from
the output while preserving every named field and row. Do not assume an
arbitrary unnamed column is disposable on a changed source.

## Selected method

Use a left join on a calculated H3 key. A left join retains every source row
even if no cell is found. For each row:

1. Resolve the actual lowercase coordinate headers, rejecting duplicate or
   ambiguous headers. Preserve identifiers, timestamps and other fields as text.
2. If either coordinate is blank after trimming, retain the row with index `0`.
   Count missing-both and missing-one separately. Handling one missing coordinate
   the same way is an explicit extension of the README's empty-field rule.
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

Supplemental geometries are mathematically derived H3 cells, not invented
locations or copied reference answers. Tag each supplemental feature with
provenance such as `source: h3_derived_coverage_gap`; include the H3 library
version and recovered request count in the report. Reverse the library's
latitude/longitude pairs to GeoJSON longitude/latitude, and close the ring.
Never alter the successful Section 1 output to hide missing source cells.

The [official H3 Python API](https://uber.github.io/h3-py/api_quick.html)
documents coordinate-to-cell and cell-to-boundary operations. That API uses
latitude/longitude; GeoJSON positions use longitude/latitude. At cell edges,
use the library's assignment consistently rather than inventing a nearest-cell
rule. Test a grid boundary point against that pinned-library behavior.

Why this method: the data is an H3 grid with verified indices and geometry,
and direct calculation matched every reference assignment in the probe. It
offers a unique cell identity and requires no additional GIS dependency.
A generic point-in-polygon spatial join remains appropriate for arbitrary or
clipped polygons, and would require decisions for boundary points and multiple
matches. It is unnecessary for this verified grid. H3 calculation alone is
not the entire method: membership, original join failures and supplemental
cells are explicitly checked and recorded.

## Error thresholds and rationale

The standalone configuration is `config/section2_policy.json`. Fractions in
that file are in [0, 1], not percentages. Never compare display-rounded rates.

Define N as all rows, M as rows with either coordinate missing, I as rows with
nonempty but invalid coordinates, and G as usable rows outside the original
grid. E = N - M is the nonmissing-coordinate denominator.

| Policy | Formula | Maximum | Observed |
| --- | --- | --- | --- |
| Original-grid unjoined rate | (M + I + G) / N | 25% | 22.553030% |
| Unexpected join error rate | (I + G) / E | 0.001% | 0.000411% |

Stop if either rate is strictly greater than its maximum. Empty inputs and
E = 0 fail explicitly instead of dividing by zero or declaring success.
Invalid coordinates also fail independently, even if the rates are low.

The total 25% cap accommodates the observed 22.552712% of missing locations
with limited headroom. It catches a substantial missing-data increase or a
broken column mapping, but is an operational policy, not a statistical bound.
Missing locations must still be visible in counts and rates, even when accepted.

The 0.001% cap permits at most seven unexpected gaps among 729,270 eligible
rows; eight would fail. The observed three gaps fit within this small tolerance.
This allows the measured source-coverage imperfection while catching grid
regressions or incorrect coordinate ordering. This tolerance is deliberately
selected after inspection, not an estimate of future reliability. Document
and review any later policy change instead of automatically widening it to pass.

Count G before fallback; successfully deriving a cell does not erase a source
coverage failure. Log both the original failure rate and the recovered count.
Require zero H3 mismatches against the reference independently of these
operational thresholds. Being below a join error threshold is not permission
to produce the wrong assignment.

## Reference validation and row preservation

The exploratory scan established that source and reference are aligned and
have unique notification numbers. The production run may compare streams in
that order, but must check the identity and every shared source field at every
position and detect extra or missing rows using a full-length comparison.
If ordering changes, fail with an alignment error; never compare unrelated rows.
A future order-independent validator would need a keyed lookup or external sort.

Keep all 15 named fields in source order and append `h3_level8_index`. Omit
only the verified sequential unnamed export index. Preserve original text
values and row order. Check notification identity uniqueness without using
it to deduplicate; a duplicate fails with a report. Do not infer numbers from
identifier strings or round source coordinates before assignment.

Compute assignment solely from source coordinates and grid membership. Access
reference rows only for validation. Compare the serialized temporary output
back to the reference before publication, so a writing error cannot evade a
comparison performed only on pre-serialization values.

## Implementation and verification handoff

Add a transformation module and focused tests, reusing shared S3 access and
logging. Provide one documented command for the combined Sections 1-2 run.
On a new checkout, the normal path must obtain and validate Section 1 output
automatically rather than require a manually prepared GeoJSON. If a separate
Section 2 command accepts a local grid, validate it and its provenance first.

Stream the compressed CSVs and output. A set for checking notification
uniqueness consumes memory proportional to the number of identifiers; do not
claim constant memory. Do not retain entire row dictionaries. The small grid
can stay in memory. Derive each uncovered cell once and reuse it.

Write transformed data to a temporary gzip file, with fixed gzip timestamp
and filename metadata for deterministic bytes. Validate that file, then publish
`data/processed/sr_hex.csv.gz`. Write the supplemental grid under `outputs/`
and include checksums and a shared run ID in `outputs/section2_validation.json`.
Stage all artifacts and publish a success report last. On interruption or
failure, report failure and prevent consumers from treating stale or partly
published artifacts as current. Multi-file publication is not made atomic
merely by using an atomic replacement for each file.

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
for final validation. Keep the expected assignment independent of the function
under test where possible.

The probe checked coordinate categories and boundary-comparison behavior with
synthetic checks. Full production tests and a fresh-environment end-to-end run
remain outstanding; the probe is not completion of the transformation task.

Interview explanation: "I checked every reference row before choosing the join.
Three valid requests belonged to two cells missing from the supplied grid.
I designed an explicit fallback using the H3 definition, retained the failure
counts, and required exact reference agreement. Missing locations stayed in
the dataset with index zero."
