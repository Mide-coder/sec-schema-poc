"""
compare_linkbases.py

Pick one debt-related concept that appears in BOTH the calculation linkbase
(_cal.xml) and the presentation linkbase (_pre.xml) of the same filing, then
show it side-by-side:

  - CALCULATION linkbase: what sums into it (parent -> children, weight, order)
    e.g. LongTermDebt = InNextTwelveMonths + InYearTwo + ... (the MATH)
  - PRESENTATION linkbase: how it's displayed on the statement (order,
    parent context) (the LAYOUT)

Key teaching point: a concept can be a summation PARENT in _cal but a single
LINE ITEM (child) in _pre -- that's exactly what happens with
us-gaap:LongTermDebt in this filing.

Usage:
    python compare_linkbases.py [path/to/_cal.xml] [path/to/_pre.xml]
    (defaults to the cached 10-K's apld-20260531_cal.xml and _pre.xml)
"""

from __future__ import annotations

import sys
from pathlib import Path

from common import (
    ATTR_FROM,
    ATTR_HREF,
    ATTR_LABEL,
    ATTR_ROLE,
    ATTR_TO,
    CLARK_LINK,
    CLARK_XLINK,
    InspectionError,
    banner,
    concept_from_href,
    default_cal_path,
    default_pre_path,
    emit_report,
    format_exception,
    is_debt_concept,
    load_xml,
)

PREFERRED_CONCEPT = "us-gaap:LongTermDebt"


class LinkbaseModel:
    """Parsed view of one linkbase: locators + parent->children arcs."""

    def __init__(self, path: Path, kind: str):
        self.path = path
        self.kind = kind  # 'calculation' | 'presentation'
        self.locations: dict[str, tuple[str, str, str]] = {}  # label -> (prefix, name, href)
        self.children: dict[str, list[dict]] = {}  # parent qname -> [child info]
        self.parents_of: dict[str, list[str]] = {}  # child qname -> [parent qnames]
        self._parse()

    def _parse(self) -> None:
        root = load_xml(self.path)

        for loc in root.iter(f"{CLARK_LINK}loc"):
            label = loc.get(ATTR_LABEL, "")
            href = loc.get(ATTR_HREF, "")
            prefix, name = concept_from_href(href)
            self.locations[label] = (prefix, name, href)

        arc_tag = f"{CLARK_LINK}calculationArc" if self.kind == "calculation" \
            else f"{CLARK_LINK}presentationArc"

        for arc in root.iter(arc_tag):
            from_label = arc.get(ATTR_FROM, "")
            to_label = arc.get(ATTR_TO, "")
            if from_label not in self.locations or to_label not in self.locations:
                continue

            p_prefix, p_name, p_href = self.locations[from_label]
            c_prefix, c_name, c_href = self.locations[to_label]
            parent = f"{p_prefix}:{p_name}" if p_prefix else p_name
            child = f"{c_prefix}:{c_name}" if c_prefix else c_name

            info = {
                "child": child,
                "order": arc.get("order", ""),
                "weight": arc.get("weight", ""),
                "preferred_label": arc.get("preferredLabel", ""),
                "child_class": "standard" if ("fasb.org" in c_href or "xbrl.sec.gov" in c_href) else "company",
            }
            self.children.setdefault(parent, []).append(info)
            self.parents_of.setdefault(child, []).append(parent)

        # Sort children by numeric order within each parent
        for parent in self.children:
            self.children[parent].sort(
                key=lambda c: (
                    int(c["order"]) if c["order"].strip().lstrip("-").isdigit() else 10**9,
                    c["order"],
                    c["child"],
                )
            )

    def qname_of(self, prefix: str, name: str) -> str:
        return f"{prefix}:{name}" if prefix else name

    def concepts(self) -> set[str]:
        return set(self.children) | set(self.parents_of)

    def is_parent(self, qname: str) -> bool:
        return qname in self.children

    def render_children(self, qname: str) -> str:
        if qname not in self.children:
            return f"      (NOT a parent in {self.kind} linkbase -- it is a leaf/line item)"
        lines = []
        for info in self.children[qname]:
            if self.kind == "calculation":
                weight_sym = "+" if float(info["weight"] or 0) >= 0 else "-"
                lines.append(
                    f"      {weight_sym} {info['child']:<52} [order={info['order']}, "
                    f"weight={info['weight']}, {info['child_class']}]"
                )
            else:
                lines.append(
                    f"      {info['child']:<52} [order={info['order']}, "
                    f"preferredLabel={info['preferred_label'] or '(default)'}]"
                )
        return "\n".join(lines)

    def render_position(self, qname: str) -> str:
        """Show where a concept sits if it is not a parent (its parent chain)."""
        parents = self.parents_of.get(qname, [])
        if not parents:
            return f"      (concept not found in {self.kind} linkbase)"
        lines = []
        for parent in sorted(parents):
            lines.append(f"      displayed under: {parent}")
        return "\n".join(lines)


def pick_concept(cal: LinkbaseModel, pre: LinkbaseModel) -> str | None:
    """
    Choose the debt-related concept to compare.

    Preference order:
      1. us-gaap:LongTermDebt if it's in both files (it usually is)
      2. any debt-related concept that is a parent in the CAL linkbase and
         present in the PRE linkbase
      3. any debt-related concept present in both files
    """
    cal_concepts = cal.concepts()
    pre_concepts = pre.concepts()
    in_both = cal_concepts & pre_concepts
    debt_in_both = sorted(c for c in in_both if is_debt_concept(c.split(":")[-1]))

    if PREFERRED_CONCEPT in in_both:
        return PREFERRED_CONCEPT

    # Prefer parents in calc with at least one child
    for c in debt_in_both:
        if cal.is_parent(c) and cal.children.get(c):
            return c
    if debt_in_both:
        return debt_in_both[0]
    return None


def compare_linkbases(cal_path: Path | str, pre_path: Path | str, *, echo: bool = True) -> str:
    cal_path = Path(cal_path)
    pre_path = Path(pre_path)

    cal = LinkbaseModel(cal_path, "calculation")
    pre = LinkbaseModel(pre_path, "presentation")

    concept = pick_concept(cal, pre)

    parts: list[str] = []
    parts.append(
        banner(
            f"CALC vs PRESENTATION LINKBASE\n"
            f"  calc: {cal_path.name}\n"
            f"  pre:  {pre_path.name}\n"
            f"  {len(cal.children)} parents / {len(pre.children)} parents parsed"
        )
    )

    if concept is None:
        parts.append("  No debt-related concept found in both linkbases.\n")
    else:
        parts.append(f"COMPARING CONCEPT: {concept}\n")
        parts.append("WHY THIS ONE: it matches debt keywords and appears in both files.\n")

        parts.append("A) CALCULATION LINKBASE -- what sums into it (the MATH)\n")
        parts.append(cal.render_children(concept))
        parts.append("")

        parts.append("B) PRESENTATION LINKBASE -- how it is displayed (the LAYOUT)\n")
        if pre.is_parent(concept):
            parts.append(pre.render_children(concept))
        else:
            parts.append(f"      '{concept}' is NOT a parent in _pre.xml; it is a line item:")
            parts.append(pre.render_position(concept))
        parts.append("")

        # Extra context: the same children that cal sums, where do they sit in pre?
        cal_children = {c["child"] for c in cal.children.get(concept, [])}
        if cal_children:
            parts.append(
                "C) THE CHILDREN THAT CAL SUMS -- where they appear in PRESENTATION\n"
            )
            for child in sorted(cal_children):
                if child in pre.parents_of:
                    parents = ", ".join(sorted(pre.parents_of[child]))
                    parts.append(f"      {child:<52} -> under: {parents}")
                elif pre.is_parent(child):
                    parts.append(f"      {child:<52} -> is a parent in pre with "
                                 f"{len(pre.children[child])} child(ren)")
                else:
                    parts.append(f"      {child:<52} -> (not in presentation linkbase)")
            parts.append("")

        parts.append(
            "KEY TAKEAWAY\n"
            "  _cal.xml encodes arithmetic relationships (what adds up to what), so a\n"
            "  parent like LongTermDebt has maturity-bucket children.  _pre.xml encodes\n"
            "  the statement LAYOUT (row order / grouping), so the same concept usually\n"
            "  appears once, as a child of an 'Abstract' or 'LineItems' parent, or as a\n"
            "  single line item.  A concept may be a parent in one linkbase and a child\n"
            "  in the other.\n"
        )

    body = "\n".join(parts)
    emit_report("linkbase_comparison.txt", "CALC VS PRESENTATION", body, echo=echo)
    return body


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if argv:
        cal_path, pre_path = argv[0], argv[1]
    else:
        cal_path, pre_path = default_cal_path(), default_pre_path()
    try:
        compare_linkbases(cal_path, pre_path)
    except InspectionError as exc:
        print(format_exception(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
