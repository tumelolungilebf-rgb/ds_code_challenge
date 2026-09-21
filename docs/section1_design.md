# Section 1: extraction and validation design

Status: design checkpoint, 21 September 2026. Extraction and validation code
have not yet been implemented. Scope remains Sections 0, 1 and 2 only.

## Purpose and evidence

Section 1 must extract resolution-8 features from the mixed-resolution file
using AWS S3 Select, compare them against the dedicated reference, calculate
a graded schema conformance score, and log operation and validation timings.
These requirements come from the original README. The rules and thresholds
below are our engineering choices, not thresholds prescribed by the assessment.

The inspection profile reports 203,840 mixed-resolution features, including
3,832 at resolution 8. The reference also has 3,832 features with unique indices.
These are observed counts, not a permanent hard-coded acceptance criterion.
They do not establish feature-by-feature equality.

The inspection of mixed-file property types used one sample. Full extracted
feature validation is still necessary. Similarly, equal CSV missing-coordinate
and zero-index counts do not establish a row-by-row match. The profiler's
`valid_pairs` means finite numeric pairs; it does not perform an individual
geographic range check, polygon join, or H3 validation. Its observed extrema
are within valid global bounds, but this is not a substitute for those checks.

## Extraction

Use bucket `cct-ds-code-challenge-input-data`, region `af-south-1`, object
`city-hex-polygons-8-10.geojson`. Proposed SQL:

```sql
SELECT *
FROM S3Object[*].features[*] AS s
WHERE s.properties.resolution = 8
```

The WHERE clause filters at S3. Return JSON with newline delimiters and use
JSON DOCUMENT input. The existing probe and inspection establish access;
this exact filtered extraction still needs an integration run.
AWS describes this JSON path and filtering syntax in its
[SELECT documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-select-sql-reference-select.html).

Consume the complete event stream, buffering partial byte records until a
newline arrives; network events need not align with JSON records or UTF-8
characters. Require the completion event and reject malformed or interrupted
responses. Close the stream even when validation fails. Any retry starts with
an empty buffer; it must not append a second response to a partial first one.

Preserve source features, including their resolution property. Build a
FeatureCollection, validate it, sort successful features by H3 index, and
write deterministic JSON via a temporary file and atomic replacement. Only
a successful run publishes the output. A failed run must have an explicit
failure report; a previous successful output must not be mistaken for new data.

Use bounded SDK connection retries and timeouts. If S3 Select becomes
unavailable, fail clearly rather than silently substitute local filtering.
The supplied credentials previously worked; new account creation is unnecessary.

## Desired schema and score

The standalone contract is `config/h3_level8_schema.json`. It is an application
configuration with documented rules, not a claim to implement the JSON Schema
standard. The validator will load it and reject unsupported contract versions,
unknown checks or invalid thresholds.

Each feature receives six equally weighted checks:

| Check | Requirement | Critical? |
| --- | --- | --- |
| Feature structure | Feature object with properties and geometry objects | Yes |
| H3 index | Valid H3 cell identifier at resolution 8 | Yes |
| Resolution field | Integer 8 | Yes |
| Polygon structure | Closed rings, finite longitude/latitude pairs, valid ranges | Yes |
| Centroid latitude | Finite number between -90 and 90 | No |
| Centroid longitude | Finite number between -180 and 180 | No |

GeoJSON places longitude before latitude and uses closed rings. The contract
uses two-dimensional positions because that is the target dataset format;
this is narrower than all formats permitted by
[RFC 7946](https://www.rfc-editor.org/rfc/rfc7946.html).
Use H3 library validation and resolution inspection, rather than string length
alone, as supported by the [H3 API](https://h3geo.org/docs/api/inspection/).

For N features, score = 100 * passed checks / (6 * N). Every check is counted,
even when a parent field is missing: dependent checks fail rather than disappear
from the denominator. Report the overall score, each rule's failure count,
and the number of fully conformant features. An empty or invalid collection
gets score 0 and fails. Duplicate indices or any critical failure also fail.
Never silently drop or repair malformed features to improve the score.

**Threshold: score >= 99.5%, evaluated before display rounding.** This is a
deliberately strict initial policy for a curated reference dataset, not a
statistically estimated error rate. It permits a small amount of auxiliary
centroid metadata incompleteness without concealing broken identifiers or
geometry. Review the policy if data ownership or requirements change.

For example, 100 features produce 600 checks. Three failed centroid checks
give 597/600 = 99.5%, passing the score gate. Four give about 99.333%, failing it.
One invalid H3 identifier fails the run regardless of the overall score.
We expect 100% on this source, but have not measured that with the new validator.

## Reference comparison is a separate acceptance check

Read `city-hex-polygons-8.geojson` independently. Require a nonempty reference
FeatureCollection, valid unique level-8 identifiers, and structurally valid
polygons. Compare key sets in both directions to find missing and extra cells.
Do not rely on feature order or silently collapse duplicate keys into a dict.

For each matching index, compare feature type, geometry type, every coordinate,
and the centroid properties. Missing required comparison paths fail; nulls
match only nulls and strings match exactly. Numeric values must be finite and
equal within an absolute tolerance of 1e-9 degrees and zero relative tolerance.
The tolerance accommodates numeric serialization differences at far below
the precision needed for this task; it does not permit meaningful changes in
location. Never round coordinates before comparison.

Preserve and compare ring and vertex order. A rotated or reversed ring may
describe the same polygon, but it fails this source-preservation comparison;
we are checking an extraction, not geometric equivalence after transformation.
Polygon structural checks do not prove absence of self-intersections.

The reference lacks `properties.resolution`, so compare shared fields and
validate that field independently on the extraction. Report additional fields
as schema drift while preserving them; they do not enter this score.

Require zero reference mismatches. Passing the quality score never overrides
a reference mismatch: source conformity and correct extraction are different
questions. Overall success requires the score threshold, critical checks,
unique identifiers, and reference equality to all pass.

## Logging, outputs and resources

Log UTC timestamps, stage, status, elapsed seconds measured with a monotonic
timer, feature counts, query, source object identifiers, sizes, ETags and
last-modified timestamps. ETags are identifiers, not assumed SHA/MD5 checksums.
Log the S3 Select scanned/processed/returned byte statistics when available.
Server-side filtering reduces returned data, not necessarily bytes scanned.

Measure credential setup, S3 extraction, reference retrieval, schema validation,
reference comparison, output write and total run separately. Log failures with
the stage and useful error category; never log credential values. Compare
source metadata before and after the run and fail if objects changed during it.

Proposed outputs: `data/processed/city-hex-polygons-8.geojson`,
`outputs/section1_validation.json`, and `outputs/pipeline.log`. These generated
files are ignored by Git; commit a short verified results summary as evidence.
Keep source files on S3; only the selected features and small reference need
local memory. Stream parsing must not buffer the 103 MB mixed source locally.

## Implementation structure and tests

Keep existing inspection scripts and documentation. Add only the modules needed:

```text
config/h3_level8_schema.json    # desired schema and acceptance policy
src/yearbeyond_pipeline/
    __main__.py               # command-line entry point
    extract.py                # S3 Select request and response parsing
    validate.py               # score and reference comparison
    sources.py                # shared S3 connection and credential loading
tests/                        # focused unit tests and explicit live integration
pyproject.toml                # package setup and dependencies
AI_log.md                     # AI requests, corrections, models and usage
```

Pin tested dependency versions and document installation and execution when
the commands exist. Proposed runtime dependencies are boto3 and h3; the
inspection helpers use Python's standard library. Add tools only if required.

Unit tests should cover: fractional scores; exact threshold boundaries; a high
score with a critical failure; absent/null/boolean/wrong-type fields; invalid
H3 cells and wrong resolution; malformed/open/out-of-range rings; empty data;
duplicates; equal counts with different indices; reordered features; altered
geometry or centroid; tolerance boundaries; response chunks split inside JSON
and multibyte text; missing stream completion; and failure before output publish.

The live integration run must execute the actual S3 Select filter and both
validations, record measurements, then verify a clean-environment invocation.
Synthetic tests establish failure behaviour; supplied references establish
correctness on the challenge data. Neither has been completed for Section 1 yet.

## Handoff to Section 2

Section 2 should consume the validated extraction. Keep the CSV header and
unnamed-column findings available for that design step. Do not infer a join
failure threshold from matching aggregate counts alone. Check missing-coordinate
rows, malformed coordinates and unmatched usable coordinates separately, and
validate assignments row by row against `sr_hex.csv.gz`.

Interview explanation: "I filtered the data at its source, defined the expected
structure separately from the code, measured conformity, and checked each result
against an independent reference. Essential errors stop processing even when
the average quality score looks good."
