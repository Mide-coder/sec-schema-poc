# APLD Schema Tracker

This tracks how APLD (CIK 0001144879) uses XBRL debt concepts across its SEC filing history. It starts with the standard US-GAAP taxonomy, then learns company-specific extensions from each filing in chronological order.

## Overview

Companies evolve their accounting vocabulary over time. APLD (Applied Digital, CIK 0001144879) creates custom XBRL concepts like `CIMPromissoryNoteMember` and `TheStarionLoanAgreementMember` for debt disclosures (loan agreements, warrant exercises, convertible notes) that do not exist in standard US-GAAP.

When processing historical filings, the system maintains strict point-in-time integrity: earlier filings are processed using only knowledge available up to that filing date, without leaking future linkbases. Filings are processed chronologically to discover relationships between company-created concepts and standard FASB concepts, producing an immutable versioned schema. Concepts are classified into five categories based on concrete evidence (calculation arc weights, namespace URIs, and dimensional relationships).

**Company history note:** All 21 filings share CIK `0001144879`. The company has renamed twice on record with the SEC: Flight Safety Technologies → Applied Science Products → **Applied Blockchain, Inc.** (2021–2023) → **Applied Digital Corp.** (2023–present). Filings from the Applied Blockchain era use the `appliedblockchaininc.com` XBRL namespace for company extensions under the same legal entity.

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
   │  14 classification rules        │
   │  (see RULES.md for full spec)   │
   └──────────────────────────────────┘
```

### Key modules

| Module | Purpose |
|--------|---------|
| `src/schema/diff_engine.py` | Classifies every debt concept into 5 categories using calc arcs, dimension arcs, namespace URIs, keyword exclusion, and debt-family relationship checks |
| `src/schema/v0_builder.py` / `src/standard_taxonomy_bootstrap.py` | Builds the v0 baseline (see "How v0 is built" below) |
| `src/schema/version_store.py` | Immutable JSON version files with hash-based no-op detection, scoped to debt-relevant arcs |
| `src/schema/schema_types.py` | Dataclasses: `Concept`, `CalcArc`, `DimensionArc`, `SchemaVersion` |
| `src/schema/graph.py` | In-memory schema graph, serializes to `SchemaVersion` |
| `src/downloader.py` | Rate-limited SEC EDGAR fetcher with atomic cache writes |
| `src/pipeline/process_filing.py` | End-to-end pipeline: load filing → diff → create version |
| `src/cli.py` | CLI: `show-schema` (by date/accession) and `show-evolution` (version diff) |
| `src/xbrl_utils.py` | Shared constants: `DEBT_KEYWORDS`, namespace classification |
| `RULES.md` | Complete specification of all 13 classification rules with real examples, including two bugs found and fixed during validation |

## How v0 is built (verified)

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

21 filings retrieved for CIK `0001144879` (single company, two prior names — see above), processed in true SEC acceptance order (see "Chronological ordering" below — this was itself a bug fix). 3 pre-XBRL filings (2008–2009) correctly skipped. 18 filings produced schema versions — 17 new versions plus one correctly-detected no-op that reuses an earlier version — on top of the v0 baseline: **18 versions total (v0–v17)**.

### Classification accuracy (final state, v17)

| Category | Count at v17 | Evidence type |
|----------|-------|--------------|
| MATCHES_STANDARD | 19 | Namespace URI (`fasb.org`) |
| Company extensions resolved | 95 | Calc arc, dimension arc, domain-member arc, presentation arc |
| Unresolved at v17 | 2 | `DebtInstrumentMandatoryPrepaymentTermsAxis`, `...Domain` — introduced by the most recent filing, no later filing yet exists to potentially resolve them |

**Total concepts at v17: 114.**

**Important nuance on "unresolved at final version":** each version's `unresolved` list reflects concepts flagged by *that specific filing's* linkbases — it is not a cumulative "still open" ledger across all history. Across the full 21-filing run, **17 distinct concepts were flagged unresolved at some point**: several were later resolved once a subsequent filing provided relationship evidence (e.g. `ClassOfWarrantOrRightGranted`, `EarlyRepaymentOfDebt`), and a smaller set remain genuinely unresolved — including the `DebtInstrumentConvertibleTermsOfConversionAxis`/`Domain`/`DebtConversionTermsOneMember` trio, a genuinely unaligned case verified against the actual filing text, not a resolved one (see RULES.md Rule 9). Treat "2 unresolved at v17" as "the current open questions as of the most recent filing processed," not "everything the system has ever flagged is now settled."

### Chronological ordering (bug found and fixed)

The pipeline originally sorted filings by accession-number **string**, not acceptance date. Because different filer agents produce different accession prefixes, this silently reordered filings — one 2022 filing was, at one point, processed using relationship evidence from filings accepted 4 years later, a direct violation of the point-in-time requirement. Fixed by sorting on the true `acceptanceDateTime` field from SEC's submissions metadata. Re-verified: a full chronological mapping table for all 21 filings, a no-future-info spot check on the now-correctly-earliest version, and byte-level reproducibility across two independent full rebuilds, all under the corrected order. See RULES.md Rule 14 for full evidence. This is the most significant of the four bugs found during validation — see below.

### Verified debt totals

The `LongTermDebt` calc tree in APLD's FY2025 10-K sums to **$869,485,000** — exactly matching the reported value. Debt-adjacent concepts (`DebtInstrumentUnamortizedDiscount`, `PaymentsOfDebtIssuanceCosts`) are correctly excluded via five independent layers of defense (see RULES.md, "Defense in Depth").

### Reproducibility

Two independent full wipes → rebuild v0 → reprocess all 21 filings, in corrected chronological order, produced **byte-identical output** across both runs — same SHA-256 checksum, file size, and content hash for all 18 version files. This was verified after all four bug fixes below, not just on the original build.

### Four real bugs found and fixed during validation

All caught through manual, evidence-based audits — not by the automated test suite passing or failing:

1. **Filings processed out of chronological order (the most significant).** The pipeline sorted by accession-number string instead of true SEC acceptance date, which silently reordered filings across different filing agents. One 2022 filing was, at one point, built on top of schema knowledge from filings accepted 4 years later — a direct violation of the point-in-time requirement. Found by insisting on a complete, filing-by-filing mapping table rather than a partial/summarized one. Fixed by sorting on `acceptanceDateTime`. See RULES.md Rule 14.
2. **Hash scope too broad.** The content hash used for no-op detection originally included *all* dimension arcs from a filing's `_def.xml`, not just debt-relevant ones — up to 152 of 268 arcs in one filing pair were unrelated noise (pension, oil & gas, accounting-standard updates). This caused every filing to look like a taxonomy change even when only unrelated areas changed. Fixed by scoping the hash to debt-relevant arcs only. See RULES.md Rule 11a.
3. **Seeding filter too permissive.** `PreferredStockConvertibleSharesIssuablePerShare` was pulled into the debt schema by keyword match (`Convertible`) despite describing preferred-stock conversion mechanics, not debt — verified by reading the actual filing text (Note 9, Redeemable Equity). Fixed by requiring a debt-family relationship, not just a keyword match, before a concept is considered a candidate. See RULES.md Rule 12.
4. **Monotonic-resolution fix over-corrected.** A fix for flip-flopping concepts (built to address bug #3's fallout) initially prevented a genuinely-resolvable concept (`ClassOfWarrantOrRightGranted`) from ever transitioning to resolved. Found by re-running the *original* manually-verified concepts as a regression check after an unrelated fix — not assuming they still held. See RULES.md Rule 13.

### Rate limiter

Stress-tested with 50 rapid-fire requests at a 5/sec limit — zero violations. Backoff recovery tested with 3 simulated 429/503 failures before success.

## Known limitations

1. **Single-company scope.** Currently tuned for APLD. The `DEBT_KEYWORDS` list and namespace classifiers would need adjustment for other filers. The architecture is company-agnostic, but the constants are APLD-specific.

2. **v0 is filing-derived, not an independent taxonomy download.** As detailed above, v0's standard-concept subgraph comes from Arelle resolving one filing's DTS, not a standalone fetch of the FASB taxonomy. In practice the result is the same (a pure-standard, zero-extension baseline), but a stricter implementation would fetch the taxonomy independently of any single filing.

3. **Amendments are excluded from the main pipeline.** The ingestion filter only accepts `form in ("10-K", "10-Q")`, so all 3 of APLD's real amendments (`10-K/A` × 2, `10-Q/A` × 1) are excluded from the 21-filing chronological run. Amendment-handling logic (Rule 10: new version created, `parent_version_id` points to the original, not the chronologically-prior version) is unit-tested against a real accession number (`0001144879-22-000043`) in `tests/test_amendments.py`, but has not been exercised end-to-end through the full, reproducibility-verified pipeline. This is a scope gap, not a correctness bug — nothing about excluding amendments affects the point-in-time or immutability guarantees for the 18 filings actually processed.

4. **`find_original_version()` amendment-matching heuristic is unproven.** Even setting aside limitation #3, the heuristic (matching on stripped accession number) would fail when an amendment and its original filing have different accession prefixes (different filing agents) — as is actually the case for APLD's `10-K/A` (`0001144879-22-000043`, direct filing) amending a 10-K submitted through an outside agent (`0001628280-22-023816`). A proper solution needs a filing-date index or EDGAR's `originalDocument` field, not accession-string matching.

5. **No temporal isolation in schema chain beyond the ordering fix.** Version IDs (v0, v1, v2...) are sequential integers tied to processing order, not calendar dates. The ordering itself is now correct (see "Chronological ordering" above), but the version IDs don't self-encode chronology — the `show-schema --date` command compensates by mapping dates to version IDs via stored filing dates rather than by the ID itself.

6. **17 concepts remain unresolved at some point across the filing history** (see the nuance note above) — flagged for human review, not silently dropped or force-matched. Three of these (the `DebtInstrumentConvertibleTermsOfConversion*` family) were manually verified as a legitimately hard case: clearly debt-relevant, but with no calc anchor to any total. Two more (`DebtInstrumentMandatoryPrepaymentTermsAxis`/`Domain`) are open specifically because they were introduced by the most recent filing processed — there's no later filing yet to test whether they'd resolve.

7. **No presentation-linkbase priority.** The system checks `parent-child` presentation arcs as a last resort (Rule 8), but doesn't use presentation order or nesting depth to disambiguate. In complex filings, presentation structure could resolve more concepts.

8. **Unresolved status is per-filing, not a cumulative open ledger.** A concept unresolved in filing N and never mentioned again in filings N+1...21 won't appear in later versions' `unresolved` lists, even though it was never actually resolved. Querying "everything ever flagged as unresolved" requires scanning history, not just reading the latest version — the CLI does not currently expose this as a single command.

## License

MIT