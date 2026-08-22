# APLD Schema Tracker

Self-healing, point-in-time XBRL schema tracker for SEC filings.

## Problem

Companies evolve their accounting vocabulary over time. APLD (Applied Digital, CIK 0001144879) creates custom XBRL concepts like `CIMPromissoryNoteMember` and `TheStarionLoanAgreementMember` that don't exist in the standard US-GAAP taxonomy. These extensions relate to debt disclosures — loan agreements, warrant exercises, convertible notes — but the relationship to standard concepts is implicit in the filing's linkbase structure, not declared explicitly.

**The core challenge:** when processing a 2022 filing, the system can only use knowledge available in 2022. It cannot use a 2025 filing's linkbase to interpret a 2022 concept. This is point-in-time integrity — the same constraint that governs financial auditing.

**What this system does:** It processes SEC XBRL filings chronologically, discovers how company-created debt concepts relate to standard FASB taxonomy concepts, and builds an immutable versioned schema that grows more complete with each filing processed. Each concept is classified into one of five categories with concrete evidence (calc arc weight, namespace URI, dimension membership) rather than heuristics.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    SEC EDGAR (source)                        │
│  XBRL filings: instance docs + calc/def/pre/lab linkbases   │
└──────────────────────┬──────────────────────────────────────┘
                       │ download (rate-limited, cached)
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  downloader.py          │  rate_limiter.py                   │
│  SEC filing fetcher     │  Token bucket, 10 req/sec         │
│  Atomic cache writes    │  Exponential backoff on 429/503   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  process_filing.py  (pipeline orchestrator)                  │
│  download → load into Arelle → diff → create version         │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
   ┌─────────────┐ ┌────────┐ ┌──────────┐
   │ diff_engine │ │ schema │ │ version  │
   │ 5-classify  │ │ graph  │ │ _store   │
   │ per concept │ │ in-mem │ │ immutable│
   └─────────────┘ └────────┘ └──────────┘
          │
          ▼
   ┌──────────────────────────────────┐
   │  11 classification rules        │
   │  (see RULES.md for full spec)   │
   └──────────────────────────────────┘
```

### Key modules

| Module | Purpose |
|--------|---------|
| `src/schema/diff_engine.py` | Classifies every debt concept into 5 categories using calc arcs, dimension arcs, namespace URIs, and keyword exclusion |
| `src/schema/version_store.py` | Immutable JSON version files with hash-based no-op detection |
| `src/schema/schema_types.py` | Frozen dataclasses: `Concept`, `CalcArc`, `DimensionArc`, `SchemaVersion` |
| `src/schema/graph.py` | In-memory schema graph, serializes to `SchemaVersion` |
| `src/downloader.py` | Rate-limited SEC EDGAR fetcher with atomic cache writes |
| `src/pipeline/process_filing.py` | End-to-end pipeline: load filing → diff → create version |
| `src/cli.py` | CLI: `show-schema` (by date/accession) and `show-evolution` (version diff) |
| `src/xbrl_utils.py` | Shared constants: `DEBT_KEYWORDS`, namespace classification |
| `RULES.md` | Complete specification of all 11 classification rules with real examples |

## Setup

```bash
# Clone
git clone <repo-url>
cd sec-schema-poc

# Python 3.11+ required
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Dependencies
pip install requests arelle-release
```

## Usage

### CLI commands

```bash
# Show schema active on a specific date
python src/cli.py show-schema --date 2024-01-15

# Show schema version used for a specific filing
python src/cli.py show-schema --accession 0001144879-24-000010

# Show what changed between versions
python src/cli.py show-evolution --from v0 --to v5
```

### HTML viewer

```bash
# Generate the interactive viewer
python src/build_viewer.py

# Open in browser (self-contained, no server needed)
start schema_viewer.html
```

### Processing a new filing

```python
from pipeline.process_filing import process_filing

# Process an APLD filing end-to-end
version = process_filing(
    cik="0001144879",
    accession="0001144879-25-000021",
    form="10-K",
)
print(f"Schema version: {version.version_id}")
```

### Running tests

```bash
# Amendment detection tests
python tests/test_amendments.py

# Restatement detection tests
python tests/test_restatements.py

# Rate limiter stress tests
python tests/test_rate_limiter_stress.py
```

## What's proven

### Classification accuracy

The system processes APLD's full filing history (13 XBRL filings across 2 CIKs) and classifies every debt-related concept:

| Category | Count | Evidence type |
|----------|-------|--------------|
| MATCHES_STANDARD | 74 | Namespace URI (`fasb.org`, `xbrl.org`) |
| NEW_EXTENSION_RESOLVED | 87 | Calc arc, dimension arc, domain-member arc, presentation arc |
| RELATED_NOT_COMBINABLE | 4 | Keyword exclusion or negative calc weight |
| NEW_EXTENSION_UNRESOLVED | 9 | No evidence found (flagged for review) |

**88% resolution rate** — down from 0% before the domain-member fix.

### Verified debt totals

The `LongTermDebt` calc tree in APLD's FY2025 10-K sums to **$869,485,000** — exactly matching the reported value. Debt-adjacent concepts (`DebtInstrumentUnamortizedDiscount`, `PaymentsOfDebtIssuanceCosts`) are correctly excluded via four independent layers of defense (see RULES.md, "Defense in Depth").

### Regression-tested

All 13 processed filings pass classification regression — 266 concepts gained resolution, 0 regressed, across the domain-member fix.

### Rate limiter

Stress-tested with 50 rapid-fire requests at 5/sec limit — zero violations. Backoff recovery tested with 3 simulated 429/503 failures before success.

## Known limitations

1. **Single-company scope.** Currently tuned for APLD (Applied Digital). The `DEBT_KEYWORDS` list and namespace classifiers would need adjustment for other filers. The architecture is company-agnostic, but the constants are APLD-specific.

2. **v0 not from actual taxonomy download.** The baseline `v0` was built by loading a filing's DTS via Arelle, not by downloading the US-GAAP taxonomy directly. This means v0 inherits whatever Arelle resolved from the filing's linkbase, which may differ from a clean taxonomy download.

3. **Amendment-to-original linking is incomplete.** The `find_original_version()` heuristic (strip `/A` from accession) fails when the amendment and original have different accession prefixes. APLD's `0001144879-22-000043` (10-K/A) amends `0001628280-22-023816` (10-K) — different CIKs. A proper solution needs a filing date index or EDGAR's `originalDocument` field.

4. **No temporal isolation in schema chain.** Versions are created sequentially (v0 → v1 → v2 → ...) regardless of filing date. A 2022 filing processed after a 2025 filing gets a higher version number. The `show-schema --date` command compensates by using filing dates, but the version IDs themselves don't encode chronology.

5. **9 unresolved concepts remain.** These are standard taxonomy concepts that appear in the instance document but have no calc/dimension arc to a known debt concept. They're flagged for human review, not silently dropped.

6. **No presentation linkbase priority.** The system checks `parent-child` presentation arcs as a last resort (Rule 8), but doesn't use presentation order or nesting depth to disambiguate. In complex filings, presentation structure could resolve more concepts.

## License

MIT
