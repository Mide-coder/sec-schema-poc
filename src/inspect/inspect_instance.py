"""Inspects XBRL instance documents and extracts debt-related facts and contexts."""

import sys
from pathlib import Path

from common import (
    CLARK_INSTANCE,
    CLARK_LINK,
    CLARK_XLINK,
    DEBT_KEYWORDS,
    InspectionError,
    banner,
    default_instance_path,
    emit_report,
    extract_namespaces,
    format_exception,
    is_debt_concept,
    load_xml,
    namespace_class,
    read_raw,
    split_qname,
)

# xbrldi explicitMember tag (namespace is stable)
XBRLDI_EXPLICIT_MEMBER = "{http://xbrl.org/2006/xbrldi}explicitMember"

# Tags that are structural, not facts
STRUCTURAL_LOCAL_TAGS = {
    "context",
    "unit",
    "schemaRef",
    "linkbaseRef",
    "roleRef",
    "arcroleRef",
}


def collect_contexts(root) -> dict[str, dict]:
    """Map context id -> {identifier, scheme, period_type, start, end, instant, segments}."""
    contexts: dict[str, dict] = {}
    for ctx in root.iter(f"{CLARK_INSTANCE}context"):
        ctx_id = ctx.get("id", "")
        info: dict = {
            "identifier": "",
            "scheme": "",
            "period_type": "",
            "start": "",
            "end": "",
            "instant": "",
            "segments": [],
        }

        entity = ctx.find(f"{CLARK_INSTANCE}entity")
        if entity is not None:
            ident = entity.find(f"{CLARK_INSTANCE}identifier")
            if ident is not None:
                info["identifier"] = (ident.text or "").strip()
                info["scheme"] = ident.get("scheme", "")

            segment = entity.find(f"{CLARK_INSTANCE}segment")
            if segment is not None:
                for member in segment.iter(XBRLDI_EXPLICIT_MEMBER):
                    dim = member.get("dimension", "")
                    value = (member.text or "").strip()
                    if dim and value:
                        info["segments"].append(f"{dim} = {value}")

        period = ctx.find(f"{CLARK_INSTANCE}period")
        if period is not None:
            instant = period.find(f"{CLARK_INSTANCE}instant")
            start = period.find(f"{CLARK_INSTANCE}startDate")
            end = period.find(f"{CLARK_INSTANCE}endDate")
            if instant is not None and instant.text:
                info["period_type"] = "instant"
                info["instant"] = instant.text.strip()
            elif start is not None and end is not None:
                info["period_type"] = "duration"
                info["start"] = (start.text or "").strip()
                info["end"] = (end.text or "").strip()

        contexts[ctx_id] = info
    return contexts


def collect_units(root) -> dict[str, str]:
    """Map unit id -> comma-joined measure list."""
    units: dict[str, str] = {}
    for unit in root.iter(f"{CLARK_INSTANCE}unit"):
        unit_id = unit.get("id", "")
        measures = []
        for measure in unit.iter(f"{CLARK_INSTANCE}measure"):
            if measure.text:
                measures.append(measure.text.strip())
        units[unit_id] = ", ".join(measures)
    return units


def build_uri_to_prefix_map(raw: str) -> dict[str, str]:
    """Map namespace URI -> prefix using the document's own xmlns declarations."""
    ns_map = extract_namespaces(raw)
    uri_to_prefix = {uri: prefix for prefix, uri in ns_map.items()}
    if not uri_to_prefix:
        # Fall back to heuristic for oddly-formed docs
        uri_to_prefix = {
            "http://fasb.org/us-gaap/2026": "us-gaap",
            "http://xbrl.sec.gov/dei/2026": "dei",
            "http://fasb.org/srt/2026": "srt",
            "http://www.xbrl.org/2003/instance": "xbrli",
        }
    return uri_to_prefix


def collect_facts(root, uri_to_prefix: dict[str, str]) -> list[tuple[str, str, str, dict]]:
    """
    Return facts as (qname, local_name, value, attributes).
    A fact is any element with a contextRef attribute that isn't structural.
    """
    facts = []
    for elem in root.iter():
        if "contextRef" not in elem.attrib:
            continue
        tag = elem.tag
        local = tag.rsplit("}", 1)[-1] if "}" in tag else tag
        if local in STRUCTURAL_LOCAL_TAGS:
            continue

        uri, local_name = split_qname(tag)
        prefix = uri_to_prefix.get(uri, "")
        qname = f"{prefix}:{local_name}" if prefix else local_name

        value = (elem.text or "").strip()
        cls = namespace_class(uri)
        facts.append(
            (
                qname,
                local_name,
                value,
                {
                    "contextRef": elem.get("contextRef", ""),
                    "unitRef": elem.get("unitRef", ""),
                    "decimals": elem.get("decimals", ""),
                    "id": elem.get("id", ""),
                    "class": cls,
                },
            )
        )
    return facts


def render_context_details(contexts: dict[str, dict], context_id: str) -> str:
    ctx = contexts.get(context_id)
    if not ctx:
        return f"      (context '{context_id}' not found in document)"
    lines = [f"      contextRef: {context_id}"]
    lines.append(f"        entity:  {ctx['identifier']}  (scheme: {ctx['scheme']})")
    if ctx["period_type"] == "instant":
        lines.append(f"        period:  instant @ {ctx['instant']}")
    elif ctx["period_type"] == "duration":
        lines.append(f"        period:  {ctx['start']} -> {ctx['end']}  (duration)")
    else:
        lines.append("        period:  (none)")
    if ctx["segments"]:
        lines.append(f"        segment: {', '.join(ctx['segments'])}")
    return "\n".join(lines)


def inspect_instance(
    instance_path: Path | str,
    concepts: list[str] | None = None,
    *,
    echo: bool = True,
) -> str:
    instance_path = Path(instance_path)
    root = load_xml(instance_path)
    uri_to_prefix = build_uri_to_prefix_map(read_raw(instance_path))

    contexts = collect_contexts(root)
    units = collect_units(root)
    facts = collect_facts(root, uri_to_prefix)

    # ---- Filter ---------------------------------------------------------
    if concepts:
        wanted = {c for c in concepts if c}
        # match full qname or bare local name
        matching = [
            f for f in facts
            if f[0] in wanted or f[1] in wanted
        ]
        mode = f"explicit concepts: {', '.join(sorted(wanted))}"
    else:
        matching = [f for f in facts if is_debt_concept(f[1])]
        mode = f"debt keywords: {', '.join(DEBT_KEYWORDS)}"

    parts: list[str] = []
    parts.append(
        banner(
            f"XBRL INSTANCE: {instance_path.name}\n"
            f"  {instance_path}\n"
            f"  Total facts in document: {len(facts)}\n"
            f"  Matching facts: {len(matching)}  ({mode})"
        )
    )

    if not matching:
        parts.append("  (no matching facts)\n")

    # Deduplicate by (qname, contextRef, unitRef) to keep output readable
    seen = set()
    for qname, local_name, value, attrs in matching:
        dedup_key = (qname, attrs["contextRef"], attrs["unitRef"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        parts.append(f"  {qname}")
        parts.append(f"      value:    {value}")
        parts.append(f"      unitRef:  {attrs['unitRef']}"
                     + (f"  ({units.get(attrs['unitRef'], 'unit not found')})" if attrs["unitRef"] else ""))
        parts.append(f"      decimals: {attrs['decimals']}")
        parts.append(f"      id:       {attrs['id']}")
        parts.append(f"      class:    {attrs['class']} "
                     f"({'standard' if attrs['class'] == 'standard' else 'COMPANY (apld)'})")
        parts.append(render_context_details(contexts, attrs["contextRef"]))
        parts.append("")

    body = "\n".join(parts)
    emit_report("instance_facts.txt", f"INSTANCE FACTS - {instance_path.name}", body, echo=echo)
    return body


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    instance_path = argv[0] if argv else default_instance_path()
    concepts = argv[1:] or None
    try:
        inspect_instance(instance_path, concepts)
    except InspectionError as exc:
        print(format_exception(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
