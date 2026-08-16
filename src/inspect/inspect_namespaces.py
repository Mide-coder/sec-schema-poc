"""
inspect_namespaces.py

List every namespace prefix declared in an XBRL file (instance, linkbase, or
schema) and what it maps to, highlighting which are standard taxonomies
(us-gaap, dei, srt, ...) versus the registrant's own namespace (apld).

Usage:
    python inspect_namespaces.py [path/to/any.xbrl-file.xml]
    (defaults to the cached 10-K instance apld-20260531_htm.xml)
"""

from __future__ import annotations

import sys
from pathlib import Path

from common import (
    InspectionError,
    banner,
    default_instance_path,
    emit_report,
    extract_namespaces,
    format_exception,
    namespace_class,
    pretty_namespace,
    read_raw,
)


def inspect_namespaces(path: Path | str, *, echo: bool = True) -> str:
    path = Path(path)
    raw = read_raw(path)  # raises InspectionError if missing/unreadable

    ns_map = extract_namespaces(raw)

    parts: list[str] = []
    parts.append(
        banner(
            f"NAMESPACE DECLARATIONS: {path.name}\n"
            f"  {path}\n"
            f"  {len(ns_map)} namespace(s) declared\n"
            f"  Legend: [standard] = FASB/SEC taxonomy (us-gaap, dei, srt);\n"
            f"          [COMPANY]  = registrant-invented (apld)\n"
            f"          [other]    = unrecognized URI"
        )
    )

    if not ns_map:
        parts.append("  (no xmlns declarations found in this file)\n")

    standard_prefixes = []
    company_prefixes = []
    other_prefixes = []

    for prefix in sorted(ns_map, key=lambda p: (p != "us-gaap" and p != "dei" and p != "srt", p)):
        uri = ns_map[prefix]
        cls = namespace_class(uri)
        if cls == "standard":
            standard_prefixes.append(prefix)
        elif cls == "company":
            company_prefixes.append(prefix)
        else:
            other_prefixes.append(prefix)
        parts.append("  " + pretty_namespace(prefix, uri))

    def display_name(prefix: str) -> str:
        return prefix if prefix else "(default)"

    parts.append("\nSUMMARY\n")
    parts.append(
        f"  Standard (FASB/SEC): {', '.join(display_name(p) for p in sorted(standard_prefixes)) or '(none)'}"
    )
    parts.append(
        f"  Company (registrant): {', '.join(display_name(p) for p in sorted(company_prefixes)) or '(none)'}"
    )
    parts.append(f"  Other: {', '.join(display_name(p) for p in sorted(other_prefixes)) or '(none)'}")

    body = "\n".join(parts)
    emit_report("namespaces.txt", f"NAMESPACES - {path.name}", body, echo=echo)
    return body


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    path = argv[0] if argv else default_instance_path()
    try:
        inspect_namespaces(path)
    except InspectionError as exc:
        print(format_exception(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
