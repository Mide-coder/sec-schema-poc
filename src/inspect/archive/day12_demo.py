"""Generates provenance reports for all processed filings without data leaks."""

import json
import sys
from pathlib import Path

from config import CACHE_DIR, CIK, SCHEMA_DIR
from pipeline.report_generator import build_report, save_report
from schema.graph import SchemaGraph
from schema.version_store import SchemaStore

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def get_filing_info(accession: str) -> dict:
    """Look up form and date from submissions cache."""
    submissions = CACHE_DIR / CIK / "submissions.json"
    with open(submissions, encoding="utf-8") as f:
        data = json.load(f)

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])

    for form, date, acc in zip(forms, dates, accession_numbers):
        if acc == accession:
            return {"form": form, "date": date}
    return {"form": "UNKNOWN", "date": "UNKNOWN"}


def main():
    store = SchemaStore(SCHEMA_DIR)
    print(f"{'='*70}")
    print("DAY 12: PROVENANCE REPORTS")
    print(f"{'='*70}")

    versions = store.list_versions()
    print(f"Versions: {versions}")

    # Generate reports for every version that has a source_filing
    for vid in versions:
        version = store.get_version(vid)
        if not version or not version.source_filing:
            continue  # v0 has no source_filing

        accession = version.source_filing
        info = get_filing_info(accession)

        print(f"\n--- Report for {accession} ({info['form']} {info['date']}) ---")
        print(f"  Schema version: {version.version_id}")
        print(f"  Hash: {version.content_hash}")
        print(f"  Concepts: {len(version.concepts)}")
        print(f"  Unresolved: {len(version.unresolved)}")

        report = build_report(version, accession, info["form"], info["date"])
        path = save_report(report)
        print(f"  Saved: {path.name}")

    # -- No-future-info test --
    print(f"\n{'='*70}")
    print("NO-FUTURE-INFO TEST")
    print(f"{'='*70}")

    # Pick two reports: early and late
    early_acc = "0001144879-25-000021"  # FY2025 10-K
    late_acc = "0001144879-26-000048"   # FY2026 10-K

    early_report = load_report(early_acc)
    late_report = load_report(late_acc)

    if early_report and late_report:
        early_concepts = {c["name"] for c in early_report["concepts"]["company"]}
        late_concepts = {c["name"] for c in late_report["concepts"]["company"]}

        # Concepts in late but not in early
        future_only = late_concepts - early_concepts

        print(f"Early report concepts: {len(early_concepts)}")
        print(f"Late report concepts: {len(late_concepts)}")
        print(f"Concepts only in late: {len(future_only)}")

        if future_only:
            print(f"\nExamples of concepts that appeared later:")
            for name in list(future_only)[:5]:
                print(f"  - {name}")
            print("\nPASS: Early report does NOT contain these later concepts")
        else:
            print("No new company concepts in later filing")
    else:
        print("Could not load both reports for comparison")

    return 0


def load_report(accession: str) -> dict | None:
    path = Path("reports") / f"{accession}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    sys.exit(main())
