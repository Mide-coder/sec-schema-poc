"""
day7_demo.py

Day 7: Test SchemaStore — load v0, verify no-op detection, immutability.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from schema.version_store import SchemaStore
from schema.graph import SchemaGraph
from schema.v0_builder import load_version

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SCHEMA_DIR = Path("schema_versions")


def main():
    print(f"{'='*60}")
    print("SCHEMA STORE DEMO")
    print(f"{'='*60}")

    # 1. Initialize store (loads existing v0.json)
    store = SchemaStore(SCHEMA_DIR)
    versions = store.list_versions()
    print(f"\nExisting versions: {versions}")

    # 2. Load v0
    v0 = store.get_version("v0")
    if v0 is None:
        print("ERROR: v0 not found. Run v0_builder.py first.")
        return 1

    print(f"\nv0 loaded:")
    print(f"  Hash:        {v0.content_hash}")
    print(f"  Concepts:    {len(v0.concepts)}")
    print(f"  Calc arcs:   {len(v0.calc_arcs)}")
    print(f"  Dim arcs:    {len(v0.dimension_arcs)}")

    # 3. No-op detection: rebuild same graph, try to create version
    print(f"\n{'='*60}")
    print("NO-OP DETECTION TEST")
    print(f"{'='*60}")
    
    graph = SchemaGraph.from_version(v0)
    result = store.create_version(
        graph=graph,
        source_filing="0001144879-25-000021",
        taxonomy_year="2025",
    )
    
    if result.version_id == "v0":
        print(f"PASS: Same hash returned existing v0 (no new version created)")
        print(f"  Hash: {result.content_hash}")
    else:
        print(f"FAIL: Created unexpected version {result.version_id}")
        return 1

    # 4. Verify no duplicate files
    versions_after = store.list_versions()
    print(f"\nVersions after no-op test: {versions_after}")
    if len(versions_after) == len(versions):
        print("PASS: No new files written")
    else:
        print("FAIL: New version files appeared")
        return 1

    # 5. Immutability check
    print(f"\n{'='*60}")
    print("IMMUTABILITY CHECK")
    print(f"{'='*60}")
    
    is_immutable = store.is_immutable("v0")
    if is_immutable:
        print("PASS: v0 is immutable (round-trip bytes identical)")
    else:
        print("FAIL: v0 appears modified or non-deterministic")
        return 1

    # 6. Query tests
    print(f"\n{'='*60}")
    print("QUERY TESTS")
    print(f"{'='*60}")
    
    by_acc = store.get_version_for_accession("0001144879-25-000021")
    print(f"By accession (0001144879-25-000021): {by_acc.version_id if by_acc else 'None'}")
    
    latest = store.get_version_for_date("2026-07-29")
    print(f"By date (2026-07-29): {latest.version_id if latest else 'None'}")

    print(f"\n{'='*60}")
    print("ALL TESTS PASSED")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())