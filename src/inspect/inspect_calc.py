"""
inspect_calc.py

Inspect a calculation linkbase (_cal.xml) and print all calculation arcs
where the parent or child concept name matches debt-related keywords.

For each arc we show:
  - parent concept (prefix:name)
  - child concept (prefix:name)
  - weight (+1.0 / -1.0)
  - order
  - whether each side is standard (us-gaap/dei/srt) or company (apld)

Usage:
    python inspect_calc.py [path/to/_cal.xml]
    (defaults to the cached 10-K's apld-20260531_cal.xml)
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from common import (
    ATTR_FROM,
    ATTR_HREF,
    ATTR_LABEL,
    ATTR_ROLE,
    ATTR_TO,
    CLARK_LINK,
    CLARK_XLINK,
    DEBT_KEYWORDS,
    InspectionError,
    banner,
    concept_from_href,
    default_cal_path,
    emit_report,
    format_exception,
    is_debt_concept,
    load_xml,
    namespace_class,
    pretty_arc_table,
)


def href_is_standard(href: str) -> str:
    """
    Classify a locator href as 'standard' or 'company'.

    Standard taxonomies live at fasb.org / xbrl.sec.gov; a registrant's own
    concepts are defined in a local schema file (e.g. apld-20260531.xsd) or
    the registrant's own domain.
    """
    if "fasb.org" in href or "xbrl.sec.gov" in href:
        return "standard"
    return "company"


class CalculationArc:
    """One calculationArc with resolved concept names."""

    def __init__(
        self,
        parent_prefix: str,
        parent_name: str,
        parent_href: str,
        child_prefix: str,
        child_name: str,
        child_href: str,
        weight: str,
        order: str,
        role: str,
    ):
        self.parent_prefix = parent_prefix
        self.parent_name = parent_name
        self.parent_href = parent_href
        self.child_prefix = child_prefix
        self.child_name = child_name
        self.child_href = child_href
        self.weight = weight
        self.order = order
        self.role = role

    @property
    def parent_qname(self) -> str:
        return f"{self.parent_prefix}:{self.parent_name}" if self.parent_prefix else self.parent_name

    @property
    def child_qname(self) -> str:
        return f"{self.child_prefix}:{self.child_name}" if self.child_prefix else self.child_name

    @property
    def parent_class(self) -> str:
        return href_is_standard(self.parent_href)

    @property
    def child_class(self) -> str:
        return href_is_standard(self.child_href)

    def is_debt_related(self) -> bool:
        return is_debt_concept(self.parent_name) or is_debt_concept(self.child_name)


def parse_calculation_arcs(cal_path: Path | str) -> list[CalculationArc]:
    """
    Parse a calculation linkbase and return ALL calculation arcs, with
    concepts resolved via the locator map.
    """
    root = load_xml(cal_path)

    # Step 1: build the locator map: label -> (prefix, name, href)
    locator_map: dict[str, tuple[str, str, str]] = {}
    for loc in root.iter(f"{CLARK_LINK}loc"):
        label = loc.get(ATTR_LABEL, "")
        href = loc.get(ATTR_HREF, "")
        prefix, name = concept_from_href(href)
        locator_map[label] = (prefix, name, href)

    # Step 2: walk each calculationLink (grouped by role) and its arcs
    arcs: list[CalculationArc] = []
    for calc_link in root.iter(f"{CLARK_LINK}calculationLink"):
        role = calc_link.get(ATTR_ROLE, "")
        for arc in calc_link.iter(f"{CLARK_LINK}calculationArc"):
            from_label = arc.get(ATTR_FROM, "")
            to_label = arc.get(ATTR_TO, "")
            weight = arc.get("weight", "")
            order = arc.get("order", "")

            parent_prefix, parent_name, parent_href = locator_map.get(
                from_label, ("", from_label, "")
            )
            child_prefix, child_name, child_href = locator_map.get(
                to_label, ("", to_label, "")
            )

            arcs.append(
                CalculationArc(
                    parent_prefix=parent_prefix,
                    parent_name=parent_name,
                    parent_href=parent_href,
                    child_prefix=child_prefix,
                    child_name=child_name,
                    child_href=child_href,
                    weight=weight,
                    order=order,
                    role=role,
                )
            )
    return arcs


def build_tree(arcs: list[CalculationArc]) -> dict[str, list[CalculationArc]]:
    """
    Group debt-related arcs by unique parent concept, children sorted by
    numeric order.
    """
    tree: dict[str, list[CalculationArc]] = {}
    for arc in arcs:
        tree.setdefault(arc.parent_qname, []).append(arc)

    for parent in tree:
        tree[parent].sort(
            key=lambda a: (
                int(a.order) if a.order.strip().lstrip("-").isdigit() else 10**9,
                a.order,
                a.child_qname,
            )
        )
    return tree


def render_tree(tree: dict[str, list[CalculationArc]]) -> str:
    if not tree:
        return "  (no matching parents)\n"
    lines = []
    for parent in sorted(tree):
        lines.append(f"  {parent}")
        for arc in tree[parent]:
            weight_sym = "+" if float(arc.weight or 0) >= 0 else "-"
            lines.append(
                f"      {weight_sym} {arc.child_qname:<55} "
                f"[order={arc.order}, weight={arc.weight}, {arc.child_class}]"
            )
    return "\n".join(lines)


def inspect_calc(cal_path: Path | str, *, echo: bool = True) -> str:
    """
    Full inspection of a calculation linkbase.  Returns the report text
    and (if echo) prints it and writes it to notes/inspection/.
    """
    cal_path = Path(cal_path)
    arcs = parse_calculation_arcs(cal_path)

    debt_arcs = [a for a in arcs if a.is_debt_related()]

    parts: list[str] = []
    parts.append(
        banner(
            f"CALCULATION LINKBASE: {cal_path.name}\n"
            f"  {cal_path}\n"
            f"  Total arcs parsed: {len(arcs)} | Debt-related arcs: {len(debt_arcs)}\n"
            f"  Keywords: {', '.join(DEBT_KEYWORDS)}\n"
            f"  NOTE: 'standard' = defined by fasb.org / xbrl.sec.gov (us-gaap, dei, srt);\n"
            f"        'company'  = defined by the registrant's own schema (apld)"
        )
    )

    # ---- Table view -----------------------------------------------------
    parts.append("1) TABLE OF DEBT-RELATED CALCULATION ARCS\n")
    table_rows = []
    for a in debt_arcs:
        table_rows.append(
            (
                a.parent_qname,
                a.child_qname,
                a.weight,
                a.order,
                a.parent_class,
                a.child_class,
            )
        )
    parts.append(pretty_arc_table(table_rows))

    # ---- Tree view ------------------------------------------------------
    parts.append("\n2) TREE VIEW (unique parents -> children, by order)\n")
    parts.append(render_tree(build_tree(debt_arcs)))

    # ---- Role breakdown -------------------------------------------------
    roles: dict[str, int] = {}
    for a in debt_arcs:
        roles[a.role] = roles.get(a.role, 0) + 1
    parts.append("\n3) DEBT ARCS BY ROLE (financial statement section)\n")
    if roles:
        for role, count in sorted(roles.items(), key=lambda kv: -kv[1]):
            short_role = role.rsplit("/", 1)[-1]
            parts.append(f"  {count:>3}  {short_role}")
    else:
        parts.append("  (none)")

    body = "\n".join(parts)
    emit_report("calc_arcs.txt", f"CALCULATION ARCS - {cal_path.name}", body, echo=echo)
    return body


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cal_path = argv[0] if argv else default_cal_path()
    try:
        inspect_calc(cal_path)
    except InspectionError as exc:
        print(format_exception(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
