"""Processes historical filings while reserving held-back subset for validation."""

import json
import sys
from pathlib import Path

from config import CACHE_DIR, CIK, SCHEMA_DIR
from pipeline.process_filing import process_filing
from schema.version_store import SchemaStore

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Hold back the 3 most recent filings for validation
HOLD_BACK_COUNT = 3


def load_filings() -> list[dict]:
    submissions = CACHE_DIR / CIK / "submissions.json"
    with open(submissions, encoding="utf-8") as f:
        data = json.load(f)

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])

    filings = []
    for form, date, acc in zip(forms, dates, accession_numbers):
        if form in ("10-K", "10-Q"):
            filings.append({"form": form, "date": date, "accession": acc})

    filings.sort(key=lambda f: f["accession"])
    return filings


def main():
    store = SchemaStore(SCHEMA_DIR)
    print(f"{'='*70}")
    print("DAY 11: FULL HISTORY (holding back 3 most recent)")
    print(f"{'='*70}")
    print(f"Versions before: {store.list_versions()}")

    filings = load_filings()
    print(f"Total 10-K/10-Q filings: {len(filings)}")

    # Hold back the most recent 3
    held_back = filings[-HOLD_BACK_COUNT:]
    to_process = filings[:-HOLD_BACK_COUNT]

    print(f"\nHeld back ({len(held_back)}):")
    for f in held_back:
        print(f"  {f['form']} {f['date']} {f['accession']}")

    print(f"\nProcessing ({len(to_process)}):")
    for f in to_process[:3]:
        print(f"  {f['form']} {f['date']} {f['accession']}")
    print(f"  ... and {len(to_process) - 3} more")

    log = []
    new_versions = 0
    no_ops = 0
    skips = 0

    for i, filing in enumerate(to_process, 1):
        accession = filing["accession"]
        print(f"\n[{i}/{len(to_process)}] {filing['form']} {filing['date']} {accession}")

        prior = store.list_versions()
        prior_latest = prior[-1] if prior else "none"

        version = process_filing(CIK, accession)

        # Reload store
        store = SchemaStore(SCHEMA_DIR)
        new_latest = store.list_versions()[-1] if store.list_versions() else "none"

        if version is None:
            print("  SKIPPED")
            skips += 1
            log.append({"accession": accession, "result": "skipped"})
        elif new_latest == prior_latest:
            print(f"  NO-OP ({prior_latest})")
            no_ops += 1
            log.append({"accession": accession, "result": "no-op", "version": prior_latest})
        else:
            print(f"  NEW VERSION: {new_latest}")
            new_versions += 1
            log.append({
                "accession": accession,
                "result": "new-version",
                "version": new_latest,
                "concepts": len(version.concepts),
                "unresolved": len(version.unresolved),
            })

    # Save log
    log_path = SCHEMA_DIR / "full_history_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({
            "held_back": [{"accession": f["accession"], "form": f["form"], "date": f["date"]} for f in held_back],
            "processed": log,
            "summary": {
                "total": len(to_process),
                "new_versions": new_versions,
                "no_ops": no_ops,
                "skips": skips,
            }
        }, f, indent=2)

    print(f"\n{'='*70}")
    print("FINAL STATE")
    print(f"{'='*70}")
    print(f"Versions: {store.list_versions()}")
    print(f"New versions: {new_versions}")
    print(f"No-ops: {no_ops}")
    print(f"Skips: {skips}")
    print(f"Log: {log_path}")

    # Sanity check: at least one no-op and one new version
    if new_versions == 0:
        print("\nWARNING: Every filing created a new version -- diff too sensitive?")
    if no_ops == 0:
        print("\nWARNING: Zero no-op filings -- diff too sensitive?")
    else:
        print("\nPASS: Both no-op and new-version filings present")

    return 0


if __name__ == "__main__":
    sys.exit(main())
