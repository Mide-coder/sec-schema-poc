# APLD Schema Tracker

Self-healing, point-in-time XBRL schema tracker for SEC filings.

## Problem

Companies evolve their accounting vocabulary over time. APLD (Applied Digital, CIK 0001144879) creates custom XBRL concepts like `CIMPromissoryNoteMember` and `TheStarionLoanAgreementMember` that don't exist in the standard US-GAAP taxonomy. These extensions relate to debt disclosures — loan agreements, warrant exercises, convertible notes — but the relationship to standard concepts is implicit in the filing's linkbase structure, not declared explicitly.

**The core challenge:** when processing a 2022 filing, the system can only use knowledge available in 2022. It cannot use a 2025 filing's linkbase to interpret a 2022 concept. This is point-in-time integrity — the same constraint that governs financial auditing.

**What this system does:** It processes SEC XBRL filings chronologically, discovers how company-created debt concepts relate to standard FASB taxonomy concepts, and builds an immutable versioned schema that grows more complete with each filing processed. Each concept is classified into one of five categories with concrete evidence (calc arc weight, namespace URI, dimension membership) rather than heuristics.

**Company history note:** all 21 filings share a single CIK, `0001144879`. The company has renamed twice on record with the SEC — Flight Safety Technologies → Applied Science Products → **Applied Blockchain, Inc.** (2021–2023) → **Applied Digital Corp.** (2023–present). Filings from the "Applied Blockchain" era use the `appliedblockchaininc.com` XBRL namespace for company extensions even though it's the same legal entity as today's APLD.

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
   │  13 classification rules        │
   │  (see RULES.md for full spec)   │
   └──────────────────────────────────┘
```

### Key modules

| Module | Purpose |
|--------|---------|
| `src/schema/diff_engine.py` | Classifies every debt concept into 5 categories using calc arcs, dimension arcs, namespace URIs, keyword exclusion, and debt-family relationship checks |
| `src/schema/v0_builder.py` / `src/standard_taxonomy_bootstrap.py` | Builds the v0 baseline (see "How v0 is built" below) |
| `src/schema/version_store.py` | Immutable JSON version files with hash-based no-op detection, scoped to debt-relevant arcs |
| `src/schema/schema_types.py` | Frozen dataclasses: `Concept`, `CalcArc`, `DimensionArc`, `SchemaVersion` |
| `src/schema/graph.py` | In-memory schema graph, serializes to `SchemaVersion` |
| `src/downloader.py` | Rate-limited SEC EDGAR fetcher with atomic cache writes |
| `src/pipeline/process_filing.py` | End-to-end pipeline: load filing → diff → create version |
| `src/cli.py` | CLI: `show-schema` (by date/accession) and `show-evolution` (version diff) |
| `src/xbrl_utils.py` | Shared constants: `DEBT_KEYWORDS`, namespace classification |
| `RULES.md` | Complete specification of all 13 classification rules with real examples, including two bugs found and fixed during validation |

## How v0 is built (verified, not assumed)

v0 is **not** built from an independent download of the FASB US-GAAP taxonomy entry point. It's derived by loading a specific APLD filing's Discoverable Taxonomy Set (DTS) through Arelle — specifically APLD's FY2025 10-K (`0001144879-25-000021`) — and extracting the standard-taxonomy-only subgraph from what Arelle resolves as part of that filing's imports (13 standard root concepts like `LongTermDebt`, `NotesPayable`, `ConvertibleDebt`, traversed via `summation-item` calc arcs to 19 standard concepts and 180 standard-to-standard calc arcs).

In practice this satisfies the brief's requirement that "the schema begins with the SEC debt taxonomy" — v0 contains only standard `us-gaap`/`fasb.org` concepts, zero company extensions, zero unresolved — but it's worth being precise: it's a taxonomy subgraph *as resolved through one filing's DTS*, not a standalone taxonomy fetch. See "Known limitations" below.

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

### Full filing history processed

21 filings retrieved for CIK `0001144879` (single company, two prior names — see above). 3 pre-XBRL filings (2008–2009) correctly skipped. 18 filings produced new schema versions (v1–v18) on top of the v0 baseline — 19 versions total.

### Classification accuracy (final state, v18)

| Category | Count at v18 | Evidence type |
|----------|-------|--------------|
| MATCHES_STANDARD | 19 | Namespace URI (`fasb.org`) |
| Company extensions resolved | 95 | Calc arc, dimension arc, domain-member arc, presentation arc |
| Unresolved at v18 | 0 | — see note below |

**Total concepts at v18: 114.**

**Important nuance on "0 unresolved":** each version's `unresolved` list reflects concepts flagged by *that specific filing's* linkbases — it is not a cumulative "still open" ledger across all history. Across the full 21-filing run, **18 distinct concepts were flagged unresolved at some point**: 6 were later resolved once a subsequent filing provided relationship evidence (e.g. `ClassOfWarrantOrRightGranted`, `EarlyRepaymentOfDebt`), and **12 remain genuinely unresolved** in the filings where they appeared — they simply don't recur in filing 21 (v18)'s own data, so they don't show up in v18's list. This includes the `DebtInstrumentConvertibleTermsOfConversionAxis`/`Domain`/`DebtConversionTermsOneMember` trio (last seen unresolved in v17), which is a genuinely unaligned case, not a resolved one — see RULES.md Rule 9 for the full evidence trail. Treat "0 unresolved at v18" as "nothing outstanding *from this specific filing*," not "everything the system has ever flagged is now resolved."

### Verified debt totals

The `LongTermDebt` calc tree in APLD's FY2025 10-K sums to **$869,485,000** — exactly matching the reported value. Debt-adjacent concepts (`DebtInstrumentUnamortizedDiscount`, `PaymentsOfDebtIssuanceCosts`) are correctly excluded via five independent layers of defense (see RULES.md, "Defense in Depth").

### Reproducibility

Two independent full wipes → rebuild v0 → reprocess all 21 filings produced **byte-identical output** across both runs — same SHA-256 checksum, file size, and content hash for all 19 version files. This was verified after the two bug fixes below, not just on the original build.

### Two real bugs found and fixed during validation

Both caught through manual, evidence-based audits — not by the automated test suite passing or failing:

1. **Hash scope too broad.** The content hash used for no-op detection originally included *all* dimension arcs from a filing's `_def.xml`, not just debt-relevant ones — up to 152 of 268 arcs in one filing pair were unrelated noise (pension, oil & gas, accounting-standard updates). This caused every filing to look like a taxonomy change even when only unrelated areas changed. Fixed by scoping the hash to debt-relevant arcs only. See RULES.md Rule 11a.
2. **Seeding filter too permissive.** `PreferredStockConvertibleSharesIssuablePerShare` was pulled into the debt schema by keyword match (`Convertible`) despite describing preferred-stock conversion mechanics, not debt — verified by reading the actual filing text (Note 9, Redeemable Equity). Fixed by requiring a debt-family relationship, not just a keyword match, before a concept is considered a candidate. See RULES.md Rule 12.

A follow-on fix for monotonic resolution (Rule 13) was itself found to have over-corrected on first pass — it's documented in RULES.md as an example of the audit process catching its own regression.

### Rate limiter

Stress-tested with 50 rapid-fire requests at a 5/sec limit — zero violations. Backoff recovery tested with 3 simulated 429/503 failures before success.

## Known limitations

1. **Single-company scope.** Currently tuned for APLD. The `DEBT_KEYWORDS` list and namespace classifiers would need adjustment for other filers. The architecture is company-agnostic, but the constants are APLD-specific.

2. **v0 is filing-derived, not an independent taxonomy download.** As detailed above, v0's standard-concept subgraph comes from Arelle resolving one filing's DTS, not a standalone fetch of the FASB taxonomy. In practice the result is the same (a pure-standard, zero-extension baseline), but a stricter implementation would fetch the taxonomy independently of any single filing.

3. **Amendment-to-original linking is incomplete.** The `find_original_version()` heuristic (strip `/A` from accession) fails when the amendment and original have different accession prefixes (different filing agents). A proper solution needs a filing-date index or EDGAR's `originalDocument` field.

4. **No temporal isolation in schema chain.** Versions are created sequentially (v0 → v1 → v2 → ...) regardless of filing date. The `show-schema --date` command compensates by using filing dates, but version IDs themselves don't encode chronology.

5. **12 concepts remain genuinely unresolved** across the filing history (see the nuance note above) — flagged for human review, not silently dropped or force-matched. Three of these (the `DebtInstrumentConvertibleTermsOfConversion*` family) were manually verified as a legitimately hard case: clearly debt-relevant, but with no calc anchor to any total.

6. **No presentation-linkbase priority.** The system checks `parent-child` presentation arcs as a last resort (Rule 8), but doesn't use presentation order or nesting depth to disambiguate. In complex filings, presentation structure could resolve more concepts.

7. **Unresolved status is per-filing, not a cumulative open ledger.** A concept unresolved in filing N and never mentioned again in filings N+1...21 won't appear in later versions' `unresolved` lists, even though it was never actually resolved. Querying "everything ever flagged as unresolved" requires scanning history, not just reading the latest version — the CLI does not currently expose this as a single command.

## License

MIT