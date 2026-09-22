# Section 1: extraction and validation design

Design recorded on 21 September 2026, before implementation. Results are in
[Section 1 results](section1_results.md) and the [final review](final_review.md).

## Purpose and evidence

Section 1 must extract resolution-8 features from the mixed-resolution file
using AWS S3 Select, compare them against the dedicated reference, calculate
a graded schema conformance score, and log operation and validation timings.
The assessment requires these checks. The specific rules and thresholds are
project design choices.

The inspection profile reports 203,840 mixed-resolution features, including
3,832 at resolution 8. The reference also has 3,832 features with unique indices.
The validator compares individual features and does not hard-code these counts.

Initial inspection sampled the mixed-file property types. Full validation must
check every extracted feature. The source profiler's `valid_pairs` count covers
finite numeric coordinates only; range checks and H3 assignment belong to the
transformation stage.

## Extraction

Use bucket `cct-ds-code-challenge-input-data`, region `af-south-1`, object
`city-hex-polygons-8-10.geojson`. Proposed SQL:

```sql
SELECT *
FROM S3Object[*].features[*] AS s
WHERE s.properties.resolution = 8
```

The WHERE clause filters at S3. Use JSON DOCUMENT input and return
newline-delimited JSON.
AWS describes this JSON path and filtering syntax in its
[SELECT documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-select-sql-reference-select.html).

Buffer incoming bytes until a complete record arrives. Network chunks can split
JSON records or UTF-8 characters. Require the completion event, reject malformed
or interrupted responses, and close the stream after processing. A retry must
start with an empty buffer.

Preserve the source features and resolution property. Validate the
FeatureCollection, sort features by H3 index, and write deterministic JSON
through a temporary file. Replace the output only after validation passes.
Record failures in the run report.

Use bounded SDK retries and timeouts. An unavailable S3 Select service must
produce a failure. Local filtering would not meet the extraction requirement.

## Desired schema and score

The standalone contract is `config/h3_level8_schema.json`. It defines the
application's validation rules rather than using the JSON Schema standard.
The validator must reject unsupported versions, unknown checks and invalid
thresholds.

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
Validate identifiers and resolution through the
[H3 API](https://h3geo.org/docs/api/inspection/).

For N features, score = 100 * passed checks / (6 * N). Missing fields fail
their checks and remain in the denominator. Report the overall score, failures
by rule and fully conformant feature count. Empty or invalid collections score
0 and fail. Duplicate indices and critical failures also fail the run.

**Minimum score: 99.5%, evaluated before rounding.** This operational threshold
allows a small number of centroid metadata failures. Identifiers and polygon
structure must pass every critical check. Reassess the threshold if the data
or requirements change.

For example, 100 features produce 600 checks. Three failed centroid checks
give 597/600 = 99.5%, passing the score gate. Four give about 99.333%, failing it.
One invalid H3 identifier fails the run regardless of the overall score.

## Reference comparison is a separate acceptance check

Read `city-hex-polygons-8.geojson` independently. Require a nonempty reference
FeatureCollection, valid unique level-8 identifiers, and structurally valid
polygons. Compare key sets in both directions to find missing and extra cells.
Compare by H3 index and reject duplicates before building a lookup.

For each matching index, compare feature type, geometry type, every coordinate,
and the centroid properties. Missing required comparison paths fail; nulls
match only nulls and strings match exactly. Numeric values must be finite and
equal within an absolute tolerance of 1e-9 degrees and zero relative tolerance.
This tolerance allows minor numeric serialization differences. Compare the
original coordinate values without rounding.

Preserve ring and vertex order to check that extraction retained the source
geometry. Rotated or reversed rings fail this comparison. Structural checks
cover ring closure and coordinate validity; they do not test self-intersections.

The reference lacks `properties.resolution`, so compare shared fields and
validate that field independently on the extraction. Report additional fields
as schema drift while preserving them; they do not enter this score.

Require zero reference mismatches. Acceptance requires the minimum schema
score, all critical checks, unique identifiers and reference agreement.

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

Outputs: `data/processed/city-hex-polygons-8.geojson`,
`outputs/section1_validation.json`, and `outputs/pipeline.log`. These generated
files are ignored by Git; commit a short verified results summary as evidence.
Keep the mixed source on S3. Local memory holds the selected features and
the level-8 reference.

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

Pin boto3 and h3 to the tested versions. Inspection helpers use Python's
standard library.

Unit tests should cover: fractional scores; exact threshold boundaries; a high
score with a critical failure; absent/null/boolean/wrong-type fields; invalid
H3 cells and wrong resolution; malformed/open/out-of-range rings; empty data;
duplicates; equal counts with different indices; reordered features; altered
geometry or centroid; tolerance boundaries; response chunks split inside JSON
and multibyte text; missing stream completion; and failure before output publish.

The live integration run must execute the actual S3 Select filter and both
validations, record measurements, then verify a clean-environment invocation.
Use synthetic tests for failure cases and the supplied reference for full-data
validation.

## Handoff to Section 2

Section 2 consumes the validated extraction. Inspect the CSV headers and
unnamed column before choosing the join policy. Count missing, malformed and
unmatched locations separately, then validate assignments against `sr_hex.csv.gz`.
