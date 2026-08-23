#!/usr/bin/env python3
"""
unresolved_audit.py

List every unresolved concept across all schema versions.
"""

import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

from schema.version_store import SchemaStore

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

store = SchemaStore(Path("schema_versions"))

# Collect all unresolved concepts across all versions
all_unresolved: list[tuple[str, str, str]] = []  # (name, version_id, source_filing)

for vid in store.list_versions():
    v = store.get_version(vid)
    if not v or not v.unresolved:
        continue
    for c in v.unresolved:
        all_unresolved.append((c.name, vid, v.source_filing or "v0-baseline"))

# Count frequency
freq = Counter(name for name, _, _ in all_unresolved)

print(f"{'='*70}")
print("UNRESOLVED CONCEPT AUDIT")
print(f"{'='*70}")
print(f"Total unresolved entries: {len(all_unresolved)}")
print(f"Unique unresolved names: {len(freq)}")
print(f"\nTop 20 most frequent unresolved concepts:")
for name, count in freq.most_common(20):
    print(f"  {count:>3}x  {name}")

# Save full list
out = Path("reports/unresolved_audit.txt")
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write("UNRESOLVED CONCEPT AUDIT\n")
    f.write("="*70 + "\n\n")
    for name, vid, src in sorted(all_unresolved):
        f.write(f"{name:<50} {vid:<6} {src}\n")
print(f"\nSaved full list: {out}")
