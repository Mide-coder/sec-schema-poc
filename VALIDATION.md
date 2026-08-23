# Validation Report

## Headline finding: the pipeline was not processing filings in true chronological order

Before restating the checklist, this needs to be stated up front rather than folded quietly into one bullet: an early version of this validation report checked the "no future information" and "unchanged taxonomy carries forward" items against a pipeline that sorted filings by **accession-number string**, not acceptance date. Because APLD's filings were submitted through different filing agents at different points (accession prefixes `0001144879-*`, `0001628280-*`, `0001898844-*`), string-sorting silently reordered filings out of true chronological sequence — one 2022 filing was, at one point, processed on top of a schema that had already learned from filings accepted 4 years later. That is a direct violation of the point-in-time requirement.

**This has been found and fixed** — sort key changed to `acceptanceDateTime` — and every checklist item below has been re-verified against the corrected chronological run. See RULES.md Rule 14 for the full before/after evidence. It's called out here, separately, because it's the single most consequential finding of the entire validation process, and it would be dishonest to bury it inside a routine-looking checklist.

## Checklis

- [x] **Schema begins with SEC debt taxonomy**
  - Evidence: v0 contains 19 standard US-GAAP concepts and 180 standard-to-standard calc arcs, extracted from the debt-relevant subgraph via Arelle's DTS resolution of APLD's FY2025 10-K entry point. Zero company extensions, zero unresolved concepts at v0. See README "How v0 is built" for the exact mechanism and its one known caveat (v0 is derived from a filing's DTS, not an independent taxonomy fetch — documented as Known Limitation #2). Unaffected by the chronology fix, since v0 is not filing-sequence-dependent.

- [x] **Company-created concepts discovered and accounted for**
  - Evidence: 95 company-extension concepts resolved into the final schema (v17, corrected chronology), each with a named resolution rule and real relationship evidence (calc arc, dimension arc, domain-member arc, or presentation arc) — see RULES.md Rules 5–8. 17 additional company/standard concepts were tracked as unresolved at some point rather than dropped or force-matched (see RULES.md Rule 9); 2 remain open at the final version.

- [x] **New taxonomy information extends the schema**
  - Evidence: 17 of 18 processed filings created a new schema version (v1–v17), each traceable to specific new concepts, calc arcs, or dimension arcs introduced by that filing, now in correct chronological order. Manually verified for two version pairs against actual filing text — see RULES.md Rule 11a for the audit confirming these changes were genuinely debt-relevant and not noise.

- [x] **Unchanged taxonomy carries same schema forward**
  - Evidence: content hash is scoped to debt-relevant concepts and arcs only (RULES.md Rule 11a). Under the corrected chronological order, this correctly surfaced a genuine no-op — filing `0001144879-24-000010` (accepted 2024-01-16) reuses the prior version rather than creating a new one, because it's chronologically adjacent to a filing with an identical debt-relevant hash. This no-op was *hidden* under the old, buggy accession-string sort order, because the two filings weren't processed back-to-back — direct evidence that the chronology fix (Rule 14) was necessary for this checklist item to be honestly claimed.

- [x] **No future information appears in earlier schema**
  - Evidence: point-in-time immutability enforced by `version_store.py` — no version file is ever mutated after being written. **Directly tested under corrected chronological order**: v1 (now correctly the earliest post-baseline version, produced from the May 2022 filing) was checked for the presence of 5 concepts known to be introduced by later filings (`ConvertibleSeniorNotesDue2030Member`, `SMBCMember`, `StarionLoanMember`, `ClassOfWarrantOrRightGranted`, `DebtInstrumentConvertibleTermsOfConversionAxis`) — all confirmed absent. This item could not have been honestly claimed under the pre-fix chronology, since a real violation existed at that time (see headline finding above).

- [x] **Historical filings remain understandable**
  - Evidence: every processed filing has a report tied to its schema version ID. Manually spot-checked for 4 concepts across different points in history (`ClassOfWarrantOrRightGranted`, `DebtConversionConvertedInstrumentSharesIssuedFairValuePerShare`, `EarlyRepaymentOfDebt`, and the unresolved convertible-terms trio) by reading the actual filing text each resolution was based on — not just checking that a report exists. Re-confirmed present and correctly classified under the corrected chronological order.

- [x] **Each extracted result identifies schema version used**
  - Evidence: every schema version file records its own version ID, content hash, and source accession number.

- [x] **Totals, components, related concepts remain correctly separated**
  - Evidence: `LongTermDebt` calc tree in APLD's FY2025 10-K sums to $869,485,000, matching the reported value exactly. Debt-adjacent-but-not-combinable concepts (`DebtInstrumentUnamortizedDiscount`, `PaymentsOfDebtIssuanceCosts`, `AmortizationOfDebtDiscountPremium`) are confirmed excluded from the calc tree via 5 independent defense layers — see RULES.md "Defense in Depth."

- [x] **Uncertain concepts are not guessed**
  - Evidence: 2 concepts (`DebtInstrumentMandatoryPrepaymentTermsAxis`/`...Domain`) remain unresolved at the final version, none force-matched. A separate, deeper case was manually audited — the `DebtInstrumentConvertibleTermsOfConversionAxis`/`Domain`/`DebtConversionTermsOneMember` trio — confirmed via filing text (Note 6, Senior Unsecured Convertible Notes) to be clearly debt-relevant but correctly left unresolved because it has no calc anchor to any total, only dimensional qualification of redemption terms.
  - Also evidenced negatively: a real false positive (`PreferredStockConvertibleSharesIssuablePerShare`) was found, root-caused, and fixed — proving the system's classifications are being checked against real evidence, not assumed correct. See RULES.md Rule 12. Re-confirmed absent under the corrected chronological order.

- [x] **Same filing history produces same result when processed again**
  - Evidence: two independent full wipes → rebuild v0 → reprocess all 21 filings, **in correct chronological order**, produced byte-identical output — same SHA-256 checksum, same file size, same content hash for all 18 version files (v0.json–v17.json). Verified after all four fixes described in RULES.md's "Known Bugs Found and Fixed," including the chronology fix — not just on the original, buggy-ordered build.

## Bugs found and fixed during validation

Documented in full in RULES.md; summarized here because they're direct evidence the validation process was substantive:

| # | Bug | How it was found | Fix | Re-verified |
|---|---|---|---|---|
| 1 | Filings processed out of chronological order — accession-string sort instead of acceptance date | Insisting on a complete, filing-by-filing mapping table rather than accepting a partial/summarized one, and noticing version numbers didn't correspond to a sane date order | Sort key changed to `acceptanceDateTime` (RULES.md Rule 14) | Yes — full mapping table regenerated, no-future-info spot check re-run, byte-level reproducibility re-run, all under corrected order |
| 2 | Content hash included non-debt dimension arcs, causing every filing to appear to change the schema | Manual diff of two consecutive version pairs against actual filing text | Hash scoped to debt-relevant arcs only (RULES.md Rule 11a) | Yes — re-diffed same pairs post-fix, confirmed only genuine debt changes remain |
| 3 | Seeding filter let an equity concept into the debt schema via keyword overlap (`Convertible`) | Manual spot-check of a resolved concept's underlying filing text (Note 9, Redeemable Equity) | Seeding now requires a debt-family relationship, not just a keyword match (RULES.md Rule 12) | Yes — confirmed absent from all 18 rebuilt versions |
| 4 | First fix for monotonic resolution over-corrected, blocking a genuinely resolvable concept (`ClassOfWarrantOrRightGranted`) from ever transitioning to resolved | Re-running the 3 originally-verified concepts as a regression check after fix #3 — not assumed to still hold | Re-check relationship evidence fresh each time instead of blindly carrying forward status (RULES.md Rule 13) | Yes — all originally-verified concepts and all flip-flop concepts re-confirmed correct |

Bug #1 is called out separately above as the headline finding because it's the only one of the four that directly threatened a core spec requirement (point-in-time integrity) rather than a classification-accuracy detail.

## Full Filing History Results (corrected chronological order)

Regenerated from `submissions.json` acceptance timestamps and on-disk `schema_versions/`, ordered oldest to newest. Replaces the earlier "Held-Back Filing Results" table, which was based on a partial (3-filing) and — it turned out — incorrectly-ordered run; that framing (staged introduction of 3 held-back filings) doesn't reflect what was actually validated, which is a full 21-filing chronological run.

| # | Acceptance Date | Form | Accession | Outcome | Version |
|---|---|---|---|---|---|
| 1 | 2008-10-22 | 10-Q | `0001376474-08-000065` | Skipped (pre-XBRL) | — |
| 2 | 2009-01-16 | 10-Q | `0001144879-09-000004` | Skipped (pre-XBRL) | — |
| 3 | 2009-04-13 | 10-Q | `0001144879-09-000013` | Skipped (pre-XBRL) | — |
| 4 | 2022-05-13 | 10-Q | `0001628280-22-014389` | New version | v1 |
| 5 | 2022-08-29 | 10-K | `0001628280-22-023816` | New version | v2 |
| 6 | 2022-10-12 | 10-Q | `0001144879-22-000052` | New version | v3 |
| 7 | 2023-01-10 | 10-Q | `0001144879-23-000028` | New version | v4 |
| 8 | 2023-04-06 | 10-Q | `0001144879-23-000101` | New version | v5 |
| 9 | 2023-08-02 | 10-K | `0001144879-23-000176` | New version | v6 |
| 10 | 2023-10-10 | 10-Q | `0001898844-23-000006` | New version | v7 |
| 11 | 2024-01-16 | 10-Q | `0001144879-24-000010` | **No-op** (identical debt-relevant hash) | reuses v7 |
| 12 | 2024-04-11 | 10-Q | `0001144879-24-000078` | New version | v8 |
| 13 | 2024-08-30 | 10-K | `0001144879-24-000216` | New version | v9 |
| 14 | 2024-10-09 | 10-Q | `0001144879-24-000253` | New version | v10 |
| 15 | 2025-01-14 | 10-Q | `0001144879-25-000006` | New version | v11 |
| 16 | 2025-04-14 | 10-Q | `0001628280-25-017684` | New version | v12 |
| 17 | 2025-07-30 | 10-K | `0001144879-25-000021` | New version | v13 |
| 18 | 2025-10-09 | 10-Q | `0001144879-25-000069` | New version | v14 |
| 19 | 2026-01-08 | 10-Q | `0001144879-26-000006` | New version | v15 |
| 20 | 2026-04-08 | 10-Q | `0001144879-26-000030` | New version | v16 |
| 21 | 2026-07-29 | 10-K | `0001144879-26-000048` | New version | v17 (final) |

**3 real amendments exist in APLD's SEC history but are not in this table** — they're excluded from the pipeline by the `form in ("10-K", "10-Q")` ingestion filter. See README Known Limitation #3 and RULES.md Rule 10 for what is and isn't proven about amendment handling.

## Known nuance: "unresolved" is per-filing, not a cumulative ledger

Worth stating explicitly here, not just in the README: a version's `unresolved` list reflects only concepts flagged by *that filing's* linkbases. A concept unresolved in filing N that never recurs in a later filing won't appear in that later version's unresolved list, even though it was never actually resolved. Across the full corrected run, 17 distinct concepts were flagged unresolved at some point; most were later genuinely resolved with new evidence, a smaller set — including the convertible-terms trio — remain open, and 2 (`DebtInstrumentMandatoryPrepaymentTermsAxis`/`Domain`) are open specifically because they were introduced by the final filing processed, with no later filing yet available to test resolution against.

## How to Verify

```bash
PYTHONPATH=src python src/inspect/validate_pipeline.py
```

Reproducibility check (must be run from a clean state to be meaningful):

```bash
rm -rf schema_versions/*.json schema_versions/*.jsonl reports/
python run_clean.py   # rebuild v0, reprocess all 21 filings in correct acceptance-date order
# save output, then repeat:
rm -rf schema_versions/*.json schema_versions/*.jsonl reports/
python run_clean.py
# diff the two runs' schema_versions/ directories — must be byte-identical
```

Confirm the sort key in `run_clean.py`'s `load_all_filings()` is `f["acceptanceDateTime"]`, not `f["accession"]`, before trusting any output — this was the source of the chronology bug (RULES.md Rule 14).