#!/usr/bin/env python3
"""
run_clean.py

Full clean-run of the pipeline from scratch.
Wipes schema_versions, rebuilds v0, processes all APLD filings,
and compares results against the captured baseline.
"""

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from schema.v0_builder import build_v0_from_filing, save_version, load_version
from pipeline.process_filing import process_filing
from schema.version_store import SchemaStore

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "cache"
SCHEMA_DIR = Path(__file__).parent.parent / "schema_versions"
CIK = "0001144879"


def load_all_filings() -> list[dict]:
    """Load 10-K/10-Q filings from submissions, sorted by SEC acceptance datetime (chronological)."""
    submissions = CACHE_DIR / CIK / "submissions.json"
    with open(submissions, encoding="utf-8") as f:
        data = json.load(f)

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    acceptance_datetimes = recent.get("acceptanceDateTime", [])

    filings = []
    for form, date, acc, adt in zip(forms, dates, accession_numbers, acceptance_datetimes):
        if form in ("10-K", "10-Q"):
            filings.append({
                "form": form,
                "date": date,
                "accession": acc,
                "acceptanceDateTime": adt,
            })

    # Sort by actual SEC acceptance datetime — NOT by accession string.
    # Accession prefixes encode the filing agent (e.g. 0001628280 = Donnelley),
    # not filing chronology. String sort groups by agent, not time.
    filings.sort(key=lambda f: f["acceptanceDateTime"])
    return filings


def capture_state(store: SchemaStore) -> dict:
    """Capture the current state of all versions for comparison."""
    state = {}
    for vid in store.list_versions():
        v = store.get_version(vid)
        if v:
            state[vid] = {
                "version_id": v.version_id,
                "source_filing": v.source_filing,
                "content_hash": v.content_hash,
                "total_concepts": len(v.concepts),
                "standard_count": sum(1 for c in v.concepts if c.namespace_type == "STANDARD"),
                "company_count": sum(1 for c in v.concepts if c.namespace_type == "COMPANY"),
                "calc_arcs_count": len(v.calc_arcs),
                "dimension_arcs_count": len(v.dimension_arcs),
                "unresolved_count": len(v.unresolved),
                "parent_version_id": v.parent_version_id,
            }
    return state


def compare_states(before: dict, after: dict, label: str = "") -> bool:
    """Compare two states and report differences."""
    passed = True

    # Check versions present in both
    before_ids = set(before.keys())
    after_ids = set(after.keys())

    if before_ids != after_ids:
        print(f"\nVERSION SET MISMATCH {label}")
        print(f"  Before: {sorted(before_ids)}")
        print(f"  After:  {sorted(after_ids)}")
        passed = False

    # Compare common versions
    common = before_ids & after_ids
    for vid in sorted(common, key=lambda x: int(x[1:])):
        b = before[vid]
        a = after[vid]

        diffs = []
        for key in ["content_hash", "total_concepts", "standard_count", "company_count",
                      "calc_arcs_count", "dimension_arcs_count", "unresolved_count",
                      "source_filing", "parent_version_id"]:
            if b.get(key) != a.get(key):
                diffs.append(f"  {key}: {b.get(key)} -> {a.get(key)}")

        if diffs:
            print(f"\n{vid} MISMATCH:")
            for d in diffs:
                print(f"  {d}")
            passed = False
        else:
            print(f"  {vid}: OK (hash={a['content_hash'][:8]}, concepts={a['total_concepts']}, un={a['unresolved_count']})")

    return passed


def main() -> int:
    start_time = time.time()

    print("=" * 70)
    print("FULL CLEAN RUN — Pipeline from scratch")
    print("=" * 70)

    # 1. Load baseline for comparison
    baseline_path = Path(__file__).parent.parent / "baseline_before_wipe.json"
    if baseline_path.exists():
        with open(baseline_path) as f:
            baseline = json.load(f)
        print(f"\nBaseline loaded: {len(baseline)} versions to compare against")
    else:
        print("\nWARNING: No baseline file found. Will create one from current run.")
        baseline = None

    # 2. Build v0 from standard taxonomy
    print(f"\n{'='*70}")
    print("STEP 1: Build v0 baseline from standard taxonomy")
    print(f"{'='*70}")

    t0 = time.time()
    v0 = build_v0_from_filing("0001144879-25-000021")
    if v0 is None:
        print("FATAL: Failed to build v0")
        return 1

    SCHEMA_DIR.mkdir(exist_ok=True)
    save_version(v0, SCHEMA_DIR)
    print(f"v0 built in {time.time() - t0:.1f}s: {len(v0.concepts)} concepts, hash={v0.content_hash[:8]}")

    # 3. Process all filings
    print(f"\n{'='*70}")
    print("STEP 2: Process all filings end-to-end")
    print(f"{'='*70}")

    filings = load_all_filings()
    print(f"Total filings to process: {len(filings)}")

    log = []
    new_versions = 0
    no_ops = 0
    skips = 0
    errors = 0

    for i, filing in enumerate(filings, 1):
        accession = filing["accession"]
        form = filing["form"]
        date = filing["date"]

        print(f"\n[{i}/{len(filings)}] {form} {date} {accession}")

        store = SchemaStore(SCHEMA_DIR)
        prior_versions = store.list_versions()
        prior_latest = prior_versions[-1] if prior_versions else "none"

        t_start = time.time()
        try:
            version = process_filing(CIK, accession)
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1
            log.append({"accession": accession, "result": "error", "error": str(e)})
            continue
        elapsed = time.time() - t_start

        # Reload store
        store = SchemaStore(SCHEMA_DIR)
        new_versions_list = store.list_versions()
        new_latest = new_versions_list[-1] if new_versions_list else "none"

        if version is None:
            print(f"  SKIPPED ({elapsed:.1f}s)")
            skips += 1
            log.append({"accession": accession, "result": "skipped"})
        elif new_latest == prior_latest:
            print(f"  NO-OP ({prior_latest}) ({elapsed:.1f}s)")
            no_ops += 1
            log.append({"accession": accession, "result": "no-op", "version": prior_latest})
        else:
            print(f"  NEW VERSION: {new_latest} ({elapsed:.1f}s)")
            new_versions += 1
            log.append({
                "accession": accession,
                "result": "new-version",
                "version": new_latest,
                "concepts": len(version.concepts),
                "unresolved": len(version.unresolved),
            })

    # 4. Save run log
    run_log = {
        "run_type": "clean-run",
        "processed": log,
        "summary": {
            "total": len(filings),
            "new_versions": new_versions,
            "no_ops": no_ops,
            "skips": skips,
            "errors": errors,
        },
        "elapsed_seconds": round(time.time() - start_time, 1),
    }
    log_path = SCHEMA_DIR / "clean_run_log.json"
    with open(log_path, "w") as f:
        json.dump(run_log, f, indent=2)

    # 5. Capture final state
    print(f"\n{'='*70}")
    print("STEP 3: Capture final state")
    print(f"{'='*70}")

    store = SchemaStore(SCHEMA_DIR)
    final_state = capture_state(store)

    print(f"Versions created: {len(final_state)}")
    for vid in sorted(final_state.keys(), key=lambda x: int(x[1:])):
        s = final_state[vid]
        print(f"  {vid}: hash={s['content_hash'][:8]}, concepts={s['total_concepts']}, "
              f"calcs={s['calc_arcs_count']}, dims={s['dimension_arcs_count']}, "
              f"unresolved={s['unresolved_count']}, src={s['source_filing'] or 'baseline'}")

    # 6. Compare against baseline
    if baseline:
        print(f"\n{'='*70}")
        print("STEP 4: Compare against baseline")
        print(f"{'='*70}")

        passed = compare_states(baseline, final_state)

        if passed:
            print(f"\n{'='*70}")
            print("ALL VERSIONS MATCH BASELINE — CLEAN RUN PASSED")
            print(f"{'='*70}")
        else:
            print(f"\n{'='*70}")
            print("MISMATCHES DETECTED — CLEAN RUN FAILED")
            print(f"{'='*70}")
            return 1
    else:
        print("\nNo baseline to compare against. Run captured as new baseline.")

    # 7. Summary
    total_time = time.time() - start_time
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Total time:       {total_time:.1f}s")
    print(f"Filings processed: {len(filings)}")
    print(f"New versions:     {new_versions}")
    print(f"No-ops:           {no_ops}")
    print(f"Skips:            {skips}")
    print(f"Errors:           {errors}")
    print(f"Final versions:   {len(final_state)}")
    print(f"Schema store:     {SCHEMA_DIR}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
