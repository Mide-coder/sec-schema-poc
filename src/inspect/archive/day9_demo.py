#!/usr/bin/env python3
"""
pipeline_test.py

Process one filing end-to-end, then re-evaluate historical.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.process_filing import process_filing
from pipeline.re_evaluate import re_evaluate_filing, save_report
from schema.version_store import SchemaStore

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

CIK = "0001144879"


def main():
    store = SchemaStore(Path("schema_versions"))
    print(f"{'='*70}")
    print("DAY 9: END-TO-END PIPELINE + RE-EVALUATION")
    print(f"{'='*70}")
    print(f"Versions before: {store.list_versions()}")

    # Process FY2025 10-K (should create v1 with company extensions)
    accession = "0001144879-25-000021"
    print(f"\n--- Processing {accession} ---")
    version = process_filing(CIK, accession)

    if version is None:
        print("ERROR: Processing failed")
        return 1

    print(f"\nResult: {version.version_id} (hash={version.content_hash})")
    print(f"  Concepts: {len(version.concepts)}")
    print(f"  COMPANY: {sum(1 for c in version.concepts if c.namespace_type == 'COMPANY')}")
    print(f"  STANDARD: {sum(1 for c in version.concepts if c.namespace_type == 'STANDARD')}")

    # Check if new version was created or no-op
    versions_after = store.list_versions()
    print(f"\nVersions after: {versions_after}")

    if len(versions_after) > len(store.list_versions()):
        print("New version created!")
    else:
        # Re-load store to see current state
        store2 = SchemaStore(Path("schema_versions"))
        print(f"Versions on disk: {store2.list_versions()}")

    # Re-evaluate: check v0's unresolved concepts against latest
    latest_id = store2._latest_version_id() if 'store2' in dir() else store._latest_version_id()
    if latest_id and latest_id != "v0":
        print(f"\n--- Re-evaluating v0 against {latest_id} ---")
        latest = store2.get_version(latest_id)
        v0_version = store2.get_version("v0")
        if v0_version and v0_version.unresolved:
            print(f"v0 unresolved: {len(v0_version.unresolved)}")
            resolved_now = [c for c in v0_version.unresolved if c.name in {x.name for x in latest.concepts}]
            print(f"Now resolved in {latest_id}: {len(resolved_now)}")
        else:
            print("v0 has no unresolved concepts (expected — v0 is pure standard taxonomy)")

        # Re-evaluate the filing that created v1
        v1_version = store2.get_version(latest_id)
        if v1_version and v1_version.unresolved:
            print(f"\nv1 has {len(v1_version.unresolved)} unresolved concepts")
            report = re_evaluate_filing(v1_version.source_filing, latest, store2)
            if report:
                print(f"Previously unresolved: {len(report.previously_unresolved)}")
                print(f"Now resolved: {len(report.now_resolved)}")
                print(f"Still unresolved: {len(report.still_unresolved)}")
                save_report(report)
            else:
                print("No historical version found for re-evaluation")

    print(f"\n{'='*70}")
    print("DAY 9 COMPLETE")
    print(f"{'='*70}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
