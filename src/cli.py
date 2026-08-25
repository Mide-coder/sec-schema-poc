"""CLI interface for inspecting schema versions and concept history."""

import argparse
import json
import sys
from pathlib import Path

from config import CACHE_DIR, SCHEMA_DIR
from schema.version_store import SchemaStore


def build_date_index(cache_dir: Path) -> dict[str, str]:
    """Build accession -> filing_date mapping from all submissions caches."""
    acc_to_date: dict[str, str] = {}
    for sub_path in cache_dir.glob("*/submissions.json"):
        try:
            data = json.load(open(sub_path))
            forms = data["filings"]["recent"]["form"]
            accs = data["filings"]["recent"]["accessionNumber"]
            dates = data["filings"]["recent"]["filingDate"]
            for acc, date in zip(accs, dates):
                acc_to_date[acc] = date
        except Exception:
            continue
    return acc_to_date


def get_version_for_date(store: SchemaStore, date_str: str, acc_to_date: dict[str, str]):
    """
    Find the schema version active on a given date.

    "Active on date X" means: the latest version whose source_filing date <= X.
    If no filing date is <= target, returns v0 (the standard taxonomy baseline).
    """
    # Build list of (filing_date, version_id) for all versions with known dates
    version_dates: list[tuple[str, str]] = []
    for vid in store.list_versions():
        v = store.get_version(vid)
        if not v or not v.source_filing:
            continue
        filing_date = acc_to_date.get(v.source_filing)
        if filing_date:
            version_dates.append((filing_date, vid))

    # Sort by date, then by version_id (so v2 before v10 for same date)
    version_dates.sort(key=lambda x: (x[0], int(x[1][1:])))

    # Find the latest version where filing_date <= target
    result_vid = None
    for filing_date, vid in version_dates:
        if filing_date <= date_str:
            result_vid = vid
        else:
            break

    if result_vid:
        return store.get_version(result_vid)

    # Fallback: return v0 baseline for dates before any filing
    return store.get_version("v0")


def get_version_for_accession(store: SchemaStore, accession: str):
    """Find the version created for a specific filing accession number."""
    return store.get_version_for_accession(accession)


def format_version(v, filing_date: str | None = None) -> str:
    """Format a SchemaVersion for display."""
    lines = []
    lines.append(f"Version:          {v.version_id}")
    lines.append(f"Parent:           {v.parent_version_id or '(none — baseline)'}")
    lines.append(f"Source filing:    {v.source_filing or '(baseline)'}")
    if filing_date:
        lines.append(f"Filing date:      {filing_date}")
    lines.append(f"Taxonomy year:    {v.taxonomy_year or '(unknown)'}")
    lines.append(f"Content hash:     {v.content_hash}")
    lines.append("")

    # Concept breakdown
    std = [c for c in v.concepts if c.namespace_type == "STANDARD"]
    comp = [c for c in v.concepts if c.namespace_type == "COMPANY"]
    lines.append(f"Concepts:         {len(v.concepts)} total ({len(std)} standard, {len(comp)} company)")
    lines.append(f"Calc arcs:        {len(v.calc_arcs)}")
    lines.append(f"Dimension arcs:   {len(v.dimension_arcs)}")
    lines.append(f"Unresolved:       {len(v.unresolved)}")
    lines.append("")

    # Standard concepts
    if std:
        lines.append("Standard concepts:")
        for c in std:
            lines.append(f"  {c.name}")
        lines.append("")

    # Company extensions
    if comp:
        lines.append("Company extensions:")
        for c in comp:
            tag = []
            if c.is_total:
                tag.append("total")
            if c.is_component:
                tag.append("component")
            suffix = f"  ({', '.join(tag)})" if tag else ""
            lines.append(f"  {c.name}{suffix}")
        lines.append("")

    # Calc arcs (first 10)
    if v.calc_arcs:
        shown = min(len(v.calc_arcs), 10)
        lines.append(f"Calc arcs (showing {shown}/{len(v.calc_arcs)}):")
        for a in v.calc_arcs[:shown]:
            lines.append(f"  {a.parent_name} -> {a.child_name}  (weight={a.weight:+.1f})")
        if len(v.calc_arcs) > shown:
            lines.append(f"  ... and {len(v.calc_arcs) - shown} more")
        lines.append("")

    # Unresolved (first 10)
    if v.unresolved:
        shown = min(len(v.unresolved), 10)
        lines.append(f"Unresolved concepts (showing {shown}/{len(v.unresolved)}):")
        for c in v.unresolved[:shown]:
            lines.append(f"  {c.name}")
        if len(v.unresolved) > shown:
            lines.append(f"  ... and {len(v.unresolved) - shown} more")

    return "\n".join(lines)


def cmd_show_schema(args):
    """Handle the show-schema subcommand."""
    store = SchemaStore(SCHEMA_DIR)

    if args.accession:
        v = get_version_for_accession(store, args.accession)
        if v is None:
            print(f"Error: No version found for accession {args.accession}", file=sys.stderr)
            sys.exit(1)

        acc_to_date = build_date_index(CACHE_DIR)
        filing_date = acc_to_date.get(args.accession)
        print(format_version(v, filing_date))

    elif args.date:
        acc_to_date = build_date_index(CACHE_DIR)
        v = get_version_for_date(store, args.date, acc_to_date)
        if v is None:
            print(f"Error: No version found active on {args.date}", file=sys.stderr)
            sys.exit(1)

        # Show the filing date for this version
        filing_date = acc_to_date.get(v.source_filing) if v.source_filing else None
        print(format_version(v, filing_date))
        print()
        print(f"(Schema active as of {args.date})")

    else:
        print("Error: Must specify --date or --accession", file=sys.stderr)
        sys.exit(1)


# ─── show-evolution ─────────────────────────────────────────────────────


def compute_version_diff(prev, curr):
    """Compute the structural diff between two SchemaVersions."""
    prev_names = {c.name for c in prev.concepts}
    curr_names = {c.name for c in curr.concepts}

    prev_unres = {c.name for c in prev.unresolved}
    curr_unres = {c.name for c in curr.unresolved}

    prev_arcs = {(a.parent_name, a.child_name): a.weight for a in prev.calc_arcs}
    curr_arcs = {(a.parent_name, a.child_name): a.weight for a in curr.calc_arcs}

    prev_dims = {(d.axis_name, d.member_name): d.member_namespace_type for d in prev.dimension_arcs}
    curr_dims = {(d.axis_name, d.member_name): d.member_namespace_type for d in curr.dimension_arcs}

    return {
        "new_concepts": sorted(curr_names - prev_names),
        "removed_concepts": sorted(prev_names - curr_names),
        "newly_resolved": sorted(prev_unres - curr_unres),
        "newly_unresolved": sorted(curr_unres - prev_unres),
        "new_calc_arcs": sorted(
            (p, c, curr_arcs[(p, c)]) for p, c in curr_arcs if (p, c) not in prev_arcs
        ),
        "removed_calc_arcs": sorted(
            (p, c) for p, c in prev_arcs if (p, c) not in curr_arcs
        ),
        "new_dim_arcs": sorted(
            (a, m, curr_dims[(a, m)]) for a, m in curr_dims if (a, m) not in prev_dims
        ),
        "removed_dim_arcs": sorted(
            (a, m) for a, m in prev_dims if (a, m) not in curr_dims
        ),
        "hash_changed": prev.content_hash != curr.content_hash,
    }


def format_step_narrative(vid, v, filing_date, form_type, diff, step_num, is_first):
    """Format one version transition as a human-readable narrative."""
    lines = []

    # Step header
    lines.append(f"Step {step_num}: {vid}")
    if v.source_filing:
        date_str = f"  filed {filing_date}" if filing_date else ""
        form_str = f"  ({form_type})" if form_type else ""
        lines.append(f"  Triggered by filing {v.source_filing}{date_str}{form_str}")
    else:
        lines.append(f"  Standard taxonomy baseline (v0)")
    lines.append("")

    if is_first:
        # Initial state
        std = sum(1 for c in v.concepts if c.namespace_type == "STANDARD")
        comp = sum(1 for c in v.concepts if c.namespace_type == "COMPANY")
        lines.append(f"  Starting state: {len(v.concepts)} concepts ({std} standard, {comp} company)")
        lines.append(f"                  {len(v.calc_arcs)} calc arcs, {len(v.dimension_arcs)} dimension arcs")
        lines.append(f"                  {len(v.unresolved)} unresolved")
        lines.append("")
        return "\n".join(lines)

    # Summarize changes
    anything_changed = False

    # New concepts
    if diff["new_concepts"]:
        anything_changed = True
        lines.append(f"  +{len(diff['new_concepts'])} new concepts:")
        for name in diff["new_concepts"][:8]:
            lines.append(f"    + {name}")
        if len(diff["new_concepts"]) > 8:
            lines.append(f"    ... and {len(diff['new_concepts']) - 8} more")
        lines.append("")

    # Removed concepts
    if diff["removed_concepts"]:
        anything_changed = True
        lines.append(f"  -{len(diff['removed_concepts'])} concepts removed:")
        for name in diff["removed_concepts"][:5]:
            lines.append(f"    - {name}")
        lines.append("")

    # Newly resolved
    if diff["newly_resolved"]:
        anything_changed = True
        n = len(diff["newly_resolved"])
        lines.append(f"  {n} concept{n != 1 and 's' or ''} resolved (moved from UNRESOLVED to RESOLVED):")
        # Categorize by resolution reason
        for name in diff["newly_resolved"][:8]:
            lines.append(f"    ~ {name}")
        if n > 8:
            lines.append(f"    ... and {n - 8} more")
        lines.append("")

    # Newly unresolved
    if diff["newly_unresolved"]:
        anything_changed = True
        n = len(diff["newly_unresolved"])
        lines.append(f"  {n} concept{n != 1 and 's' or ''} became unresolved (new company extensions without arcs to known concepts):")
        for name in diff["newly_unresolved"][:5]:
            lines.append(f"    ! {name}")
        if n > 5:
            lines.append(f"    ... and {n - 5} more")
        lines.append("")

    # New calc arcs
    if diff["new_calc_arcs"]:
        anything_changed = True
        lines.append(f"  +{len(diff['new_calc_arcs'])} new calculation arcs:")
        for parent, child, weight in diff["new_calc_arcs"][:5]:
            lines.append(f"    + {parent} -> {child} (weight={weight:+.1f})")
        if len(diff["new_calc_arcs"]) > 5:
            lines.append(f"    ... and {len(diff['new_calc_arcs']) - 5} more")
        lines.append("")

    # Removed calc arcs
    if diff["removed_calc_arcs"]:
        anything_changed = True
        lines.append(f"  -{len(diff['removed_calc_arcs'])} calculation arcs removed:")
        for parent, child in diff["removed_calc_arcs"][:5]:
            lines.append(f"    - {parent} -> {child}")
        lines.append("")

    # New dimension arcs
    if diff["new_dim_arcs"]:
        anything_changed = True
        lines.append(f"  +{len(diff['new_dim_arcs'])} new dimension arcs:")
        for axis, member, ns in diff["new_dim_arcs"][:5]:
            lines.append(f"    + {axis} -> {member} ({ns})")
        if len(diff["new_dim_arcs"]) > 5:
            lines.append(f"    ... and {len(diff['new_dim_arcs']) - 5} more")
        lines.append("")

    # Removed dimension arcs
    if diff["removed_dim_arcs"]:
        anything_changed = True
        lines.append(f"  -{len(diff['removed_dim_arcs'])} dimension arcs removed:")
        for axis, member in diff["removed_dim_arcs"][:5]:
            lines.append(f"    - {axis} -> {member}")
        lines.append("")

    # Hash status
    if diff["hash_changed"]:
        lines.append(f"  Content hash changed: {v.content_hash}")
    else:
        lines.append(f"  Content hash unchanged (structural equivalence)")
    lines.append("")

    # Net summary
    total_in = (
        len(diff["new_concepts"]) + len(diff["newly_unresolved"])
        + len(diff["new_calc_arcs"]) + len(diff["new_dim_arcs"])
    )
    total_out = (
        len(diff["removed_concepts"]) + len(diff["newly_resolved"])
        + len(diff["removed_calc_arcs"]) + len(diff["removed_dim_arcs"])
    )
    if not anything_changed:
        lines.append("  No structural changes detected.")
        lines.append("")

    return "\n".join(lines)


def cmd_show_evolution(args):
    """Handle the show-evolution subcommand."""
    store = SchemaStore(SCHEMA_DIR)
    acc_to_date = build_date_index(CACHE_DIR)

    # Load filing form types from submissions
    acc_to_form: dict[str, str] = {}
    for sub_path in CACHE_DIR.glob("*/submissions.json"):
        try:
            data = json.load(open(sub_path))
            forms = data["filings"]["recent"]["form"]
            accs = data["filings"]["recent"]["accessionNumber"]
            for acc, form in zip(accs, forms):
                acc_to_form[acc] = form
        except Exception:
            continue

    from_vid = args.from_version
    to_vid = args.to_version

    # Validate versions exist
    from_v = store.get_version(from_vid)
    to_v = store.get_version(to_vid)
    if from_v is None:
        print(f"Error: Version {from_vid} not found", file=sys.stderr)
        sys.exit(1)
    if to_v is None:
        print(f"Error: Version {to_vid} not found", file=sys.stderr)
        sys.exit(1)

    # Walk the chain: build path from from_vid to to_vid
    # First, build parent->child map
    all_versions = store.list_versions()
    parent_to_children: dict[str, list[str]] = {}
    for vid in all_versions:
        v = store.get_version(vid)
        if v and v.parent_version_id:
            parent_to_children.setdefault(v.parent_version_id, []).append(vid)

    # BFS from from_vid to to_vid
    from_num = int(from_vid[1:])
    to_num = int(to_vid[1:])

    # Collect the chain (sorted by version number)
    chain = []
    for vid in all_versions:
        num = int(vid[1:])
        if from_num <= num <= to_num:
            chain.append(vid)
    chain.sort(key=lambda x: int(x[1:]))

    if not chain:
        print(f"Error: No versions found between {from_vid} and {to_vid}", file=sys.stderr)
        sys.exit(1)

    # Print header
    print("=" * 70)
    print("SCHEMA EVOLUTION REPORT")
    print(f"From {from_vid} to {to_vid} ({len(chain)} versions)")
    print("=" * 70)
    print()

    # Print summary stats
    from_v = store.get_version(chain[0])
    to_v = store.get_version(chain[-1])
    print(f"Starting state ({chain[0]}):")
    std0 = sum(1 for c in from_v.concepts if c.namespace_type == "STANDARD")
    comp0 = sum(1 for c in from_v.concepts if c.namespace_type == "COMPANY")
    print(f"  {len(from_v.concepts)} concepts ({std0} standard, {comp0} company)")
    print(f"  {len(from_v.calc_arcs)} calc arcs, {len(from_v.dimension_arcs)} dimension arcs")
    print(f"  {len(from_v.unresolved)} unresolved")
    print()
    print(f"Final state ({chain[-1]}):")
    stdf = sum(1 for c in to_v.concepts if c.namespace_type == "STANDARD")
    compf = sum(1 for c in to_v.concepts if c.namespace_type == "COMPANY")
    print(f"  {len(to_v.concepts)} concepts ({stdf} standard, {compf} company)")
    print(f"  {len(to_v.calc_arcs)} calc arcs, {len(to_v.dimension_arcs)} dimension arcs")
    print(f"  {len(to_v.unresolved)} unresolved")
    print()
    print("-" * 70)
    print()

    # Print each step
    for i, vid in enumerate(chain):
        v = store.get_version(vid)
        filing_date = acc_to_date.get(v.source_filing) if v.source_filing else None
        form_type = acc_to_form.get(v.source_filing) if v.source_filing else None

        if i == 0:
            # First version: show initial state
            print(format_step_narrative(vid, v, filing_date, form_type, None, i, is_first=True))
        else:
            # Compute diff from previous version
            prev_vid = chain[i - 1]
            prev_v = store.get_version(prev_vid)
            diff = compute_version_diff(prev_v, v)
            print(format_step_narrative(vid, v, filing_date, form_type, diff, i, is_first=False))

        if i < len(chain) - 1:
            print("  |")
            print("  v")
            print()

    # Final summary
    print("=" * 70)
    print("NET CHANGE SUMMARY")
    print("=" * 70)
    total_concepts_added = sum(
        len(compute_version_diff(store.get_version(chain[i - 1]), store.get_version(vid))["new_concepts"])
        for i, vid in enumerate(chain) if i > 0
    )
    total_resolved = sum(
        len(compute_version_diff(store.get_version(chain[i - 1]), store.get_version(vid))["newly_resolved"])
        for i, vid in enumerate(chain) if i > 0
    )
    total_newly_unres = sum(
        len(compute_version_diff(store.get_version(chain[i - 1]), store.get_version(vid))["newly_unresolved"])
        for i, vid in enumerate(chain) if i > 0
    )
    total_calc_added = sum(
        len(compute_version_diff(store.get_version(chain[i - 1]), store.get_version(vid))["new_calc_arcs"])
        for i, vid in enumerate(chain) if i > 0
    )
    total_dim_added = sum(
        len(compute_version_diff(store.get_version(chain[i - 1]), store.get_version(vid))["new_dim_arcs"])
        for i, vid in enumerate(chain) if i > 0
    )
    print(f"  Concepts added:        {total_concepts_added}")
    print(f"  Concepts resolved:     {total_resolved}")
    print(f"  Concepts unresolved:   {total_newly_unres}")
    print(f"  Calc arcs added:       {total_calc_added}")
    print(f"  Dimension arcs added:  {total_dim_added}")
    print()

    # Unresolved trend
    print("  Unresolved trend:")
    for vid in chain:
        v = store.get_version(vid)
        bar = "#" * min(len(v.unresolved), 50)
        print(f"    {vid}: {len(v.unresolved):>3}  {bar}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="SEC Schema Inspector — query schema versions by date or filing",
    )
    subparsers = parser.add_subparsers(dest="command")

    show = subparsers.add_parser("show-schema", help="Show the schema active on a date or used for a filing")
    show.add_argument("--date", help="Show schema active on this date (YYYY-MM-DD)")
    show.add_argument("--accession", help="Show schema version used for this accession number")
    show.set_defaults(func=cmd_show_schema)

    evo = subparsers.add_parser("show-evolution", help="Show what changed between two schema versions")
    evo.add_argument("--from", dest="from_version", required=True, help="Starting version ID (e.g., v1)")
    evo.add_argument("--to", dest="to_version", required=True, help="Ending version ID (e.g., v5)")
    evo.set_defaults(func=cmd_show_evolution)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
