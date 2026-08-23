#!/usr/bin/env python3
"""
run_fix3 Verification

Wipe schema_versions, rebuild v0, reprocess all APLD filings end-to-end.
Capture state for comparison and determinism check.
"""

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from schema.v0_builder import build_v0_from_filing, save_version
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


def main() -> int:
    start_time = time.time()

    print("=" * 70)
    print("FIX 3 VERIFICATION — Full pipeline from scratch")
    print("=" * 70)

    # 1. Build v0 from standard taxonomy
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
    print(f"v0 built in {time.time() - t0:.1f}s: {len(v0.concepts)} concepts, hash={v0.content_hash[:12]}")

    # 2. Process all filings
    print(f"\n{'='*70}")
    print("STEP 2: Process all filings end-to-end")
    print(f"{'='*70}")

    filings = load_all_filings()
    print(f"Total filings to process: {len(filings)}")

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
            continue
        elapsed = time.time() - t_start

        store = SchemaStore(SCHEMA_DIR)
        new_versions_list = store.list_versions()
        new_latest = new_versions_list[-1] if new_versions_list else "none"

        if version is None:
            print(f"  SKIPPED ({elapsed:.1f}s)")
            skips += 1
        elif new_latest == prior_latest:
            print(f"  NO-OP ({prior_latest}) ({elapsed:.1f}s)")
            no_ops += 1
        else:
            print(f"  NEW VERSION: {new_latest} ({elapsed:.1f}s)")
            new_versions += 1

    # 3. Capture final state
    print(f"\n{'='*70}")
    print("STEP 3: Capture final state")
    print(f"{'='*70}")

    store = SchemaStore(SCHEMA_DIR)
    final_state = capture_state(store)

    print(f"Versions created: {len(final_state)}")
    for vid in sorted(final_state.keys(), key=lambda x: int(x[1:])):
        s = final_state[vid]
        print(f"  {vid}: hash={s['content_hash'][:12]}, concepts={s['total_concepts']}, "
              f"calcs={s['calc_arcs_count']}, dims={s['dimension_arcs_count']}, "
              f"unresolved={s['unresolved_count']}, src={s['source_filing'] or 'baseline'}")

    # 4. Save state for comparison
    state_path = SCHEMA_DIR / "fix3_run_state.json"
    with open(state_path, "w") as f:
        json.dump(final_state, f, indent=2)
    print(f"\nState saved to {state_path}")

    # 5. Summary
    elapsed = time.time() - start_time
    total_concepts = final_state.get(max(final_state.keys(), key=lambda x: int(x[1:])), {}).get("total_concepts", 0)
    total_unresolved_history = sum(s["unresolved_count"] for s in final_state.values())
    final_unresolved = final_state.get(max(final_state.keys(), key=lambda x: int(x[1:])), {}).get("unresolved_count", 0)

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"  Total versions: {len(final_state)}")
    print(f"  New versions:   {new_versions}")
    print(f"  No-ops:         {no_ops}")
    print(f"  Skipped:        {skips}")
    print(f"  Errors:         {errors}")
    print(f"  Final concepts: {total_concepts}")
    print(f"  Final unresolved: {final_unresolved}")
    print(f"  Total unresolved across history: {total_unresolved_history}")
    print(f"  Elapsed: {elapsed:.1f}s")

    return 0


if __name__ == "__main__":
    sys.exit(main())
