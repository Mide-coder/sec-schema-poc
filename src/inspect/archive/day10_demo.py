
"""
day10_demo.py

Day 10: Process APLD's filing history sequentially.
Shows schema evolution, no-op detection, and version log.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.process_filing import process_filing
from schema.version_store import SchemaStore
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

CIK = "0001144879"
CACHE_DIR = Path("cache")
SCHEMA_DIR = Path("schema_versions")


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

    # Sort oldest first (accession numbers are roughly chronological)
    filings.sort(key=lambda f: f["accession"])
    return filings


def main():
    store = SchemaStore(SCHEMA_DIR)
    print(f"{'='*70}")
    print("DAY 10: SEQUENTIAL PROCESSING")
    print(f"{'='*70}")
    print(f"Versions before: {store.list_versions()}")

    filings = load_filings()
    print(f"Total 10-K/10-Q filings: {len(filings)}")

    # Process first 6 filings (oldest to newest)
    target = filings[:6]
    log = []

    for filing in target:
        accession = filing["accession"]
        print(f"\n--- {filing['form']} {filing['date']} {accession} ---")

        prior_versions = store.list_versions()
        prior_latest = prior_versions[-1] if prior_versions else "none"

        version = process_filing(CIK, accession)

        if version is None:
            print("  SKIPPED (download/load failed)")
            log.append({
                "accession": accession,
                "form": filing["form"],
                "date": filing["date"],
                "result": "skipped",
            })
            continue

        # Reload store to pick up new version
        store = SchemaStore(SCHEMA_DIR)
        new_versions = store.list_versions()
        new_latest = new_versions[-1]

        if new_latest == prior_latest:
            print(f"  NO-OP (reused {prior_latest})")
            log.append({
                "accession": accession,
                "form": filing["form"],
                "date": filing["date"],
                "result": "no-op",
                "version": prior_latest,
            })
        else:
            print(f"  NEW VERSION: {new_latest}")
            print(f"    Concepts: {len(version.concepts)}")
            print(f"    COMPANY: {sum(1 for c in version.concepts if c.namespace_type == 'COMPANY')}")
            print(f"    STANDARD: {sum(1 for c in version.concepts if c.namespace_type == 'STANDARD')}")
            print(f"    Unresolved: {len(version.unresolved)}")
            log.append({
                "accession": accession,
                "form": filing["form"],
                "date": filing["date"],
                "result": "new-version",
                "version": new_latest,
                "concepts": len(version.concepts),
                "company": sum(1 for c in version.concepts if c.namespace_type == "COMPANY"),
                "unresolved": len(version.unresolved),
            })

    # Save log
    log_path = SCHEMA_DIR / "version_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)

    print(f"\n{'='*70}")
    print("FINAL STATE")
    print(f"{'='*70}")
    print(f"Versions: {store.list_versions()}")
    print(f"Log saved: {log_path}")

    # Show summary
    new_count = sum(1 for e in log if e["result"] == "new-version")
    no_op_count = sum(1 for e in log if e["result"] == "no-op")
    skip_count = sum(1 for e in log if e["result"] == "skipped")
    print(f"\nNew versions: {new_count}")
    print(f"No-op (reused): {no_op_count}")
    print(f"Skipped: {skip_count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
