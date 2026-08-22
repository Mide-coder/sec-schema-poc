# Validation Report

## Checklist (from project brief)

- [x] Schema begins with SEC debt taxonomy
  - Evidence: v0 contains 19 standard US-GAAP debt concepts, 180 calc arcs
- [x] Company-created concepts discovered and accounted for
  - Evidence: v1-v10 track unresolved company extensions per filing
- [x] New taxonomy information extends the schema
  - Evidence: new versions created across filings when new arcs appear
- [x] Unchanged taxonomy carries same schema forward
  - Evidence: no-op filings reuse existing versions
- [x] No future information appears in earlier schema
  - Evidence: no-future-info regression test passes
- [x] Historical filings remain understandable
  - Evidence: Each filing has a report tied to its schema version ID
- [x] Each extracted result identifies schema version used
  - Evidence: Every report has schema_version.id and schema_version.hash
- [x] Totals, components, related concepts remain correctly separated
  - Evidence: Calc trees show weights (+1.0), NOT_COMBINABLE filtered separately
- [x] Uncertain concepts are not guessed
  - Evidence: UNRESOLVED concepts tracked, no forced alignment
- [x] Same filing history produces same result when processed again
  - Evidence: test_reproducibility.py verifies stable hashes

## Held-Back Filing Results

| Filing | Result | Version |
|--------|--------|----------|
| 0001628280-22-023816 | new-version | v11 |
| 0001628280-25-017684 | no-op | v11 |
| 0001898844-23-000006 | no-op | v11 |

## How to Verify

```bash
PYTHONPATH=src python src/inspect/day13_validation.py
```
