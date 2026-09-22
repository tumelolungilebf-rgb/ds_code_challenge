# Section 1 verified results

Verified on 21 September 2026 with Python 3.12.14, boto3 1.43.98 and
h3 4.5.0. This records the Section 1 implementation checkpoint. The
[final review](final_review.md) contains the latest combined verification.
Generated outputs are excluded from Git. After installation, run:

```powershell
.venv\Scripts\yearbeyond-section1.exe
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

S3 Select scanned the complete source and returned about 1.86% of its size.
This reduced data transfer and local processing. Runtime depends on network
and service conditions.

The generated GeoJSON SHA-256 was identical on both live runs:

```text
83C8A05B4F9B3528892EE75968B01F4FD4986F4BFC0E1C06D2F382B8671E489B
```

Both runs produced identical output bytes. The reports also recorded source
size, ETag and last-modified metadata before and after processing. ETags were
used as object identifiers.

## Automated tests

Command:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

All 20 tests at this checkpoint passed. They cover stream chunks split inside JSON and UTF-8 text,
missing completion events, malformed records, the exact 99.5% score boundary,
critical failures overriding high scores, duplicates, missing fields, boolean
values supplied as numbers, open polygons, empty data, reordered features,
equal counts with different indices, coordinate tolerance, changed geometry,
reference duplicates, atomic publication, and preservation of a previous
successful output when a later run fails.

## Output locations

- `data/processed/city-hex-polygons-8.geojson`: validated grid.
- `outputs/section1_validation.json`: detailed result and timing report.
- `outputs/pipeline.log`: structured JSON event log.

These locations are ignored by Git. A failed run returns a nonzero exit code,
writes a failure report with `output_published: false`, and does not replace a
previous successful GeoJSON file.
