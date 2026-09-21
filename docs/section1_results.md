# Section 1 verified results

Verified on 21 September 2026 with Python 3.12.14, boto3 1.43.98 and
h3 4.5.0. The runtime outputs are intentionally ignored by Git and can be
recreated with:

```powershell
yearbeyond-section1
```

## Live extraction and validation

The pipeline executed this S3 Select query against
`city-hex-polygons-8-10.geojson` in `af-south-1`:

```sql
SELECT *
FROM S3Object[*].features[*] AS s
WHERE s.properties.resolution = 8
```

Observed results:

| Measure | Result |
| --- | ---: |
| Extracted resolution-8 features | 3,832 |
| Schema checks | 22,992 |
| Passed schema checks | 22,992 |
| Conformance score | 100% |
| Critical failures | 0 |
| Duplicate H3 indices | 0 |
| Missing reference indices | 0 |
| Extra reference indices | 0 |
| Features differing from reference | 0 |
| Source objects unchanged during run | Yes |
| Bytes scanned and processed by S3 Select | 108,254,980 |
| Bytes returned by S3 Select | 2,011,878 |
| First measured total runtime | 5.525689 seconds |
| Repeat measured total runtime | 4.369089 seconds |

S3 Select scanned the complete source object but returned about 1.86% of its
size. The optimisation here is chiefly reduced transfer and local processing,
not reduced source bytes scanned. Timing varies with network and service
conditions; two observations are evidence of these runs, not a benchmark.

The generated GeoJSON SHA-256 was identical on both live runs:

```text
83C8A05B4F9B3528892EE75968B01F4FD4986F4BFC0E1C06D2F382B8671E489B
```

This confirms deterministic feature ordering and serialization for the source
version used in these runs. The validation reports also recorded object size,
ETag and last-modified metadata before and after each run. ETags were treated
as object identifiers, not assumed to be content hashes.

## Automated tests

Command:

```powershell
python -m unittest discover -s tests -v
```

All 20 tests passed. They cover stream chunks split inside JSON and UTF-8 text,
missing completion events, malformed records, the exact 99.5% score boundary,
critical failures overriding high scores, duplicates, missing fields, boolean
values masquerading as numbers, open polygons, empty data, reordered features,
equal counts with different indices, coordinate tolerance, changed geometry,
reference duplicates, atomic publication, and preservation of a previous
successful output when a later run fails.

## Output locations

- `data/processed/city-hex-polygons-8.geojson`: deterministic successful output.
- `outputs/section1_validation.json`: detailed result and timing report.
- `outputs/pipeline.log`: structured JSON event log.

These locations are ignored by Git. A failed run returns a nonzero exit code,
writes a failure report with `output_published: false`, and does not replace a
previous successful GeoJSON file.
