"""Shared XML and linkbase inspection helpers for XBRL files."""

import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from config import CACHE_DIR, CIK, PROJECT_ROOT

NOTES_DIR = PROJECT_ROOT / "notes"

# The 10-K filing from the local cache
TARGET_ACCESSION = "0001144879-26-000048"
TARGET_FILING_DIR = CACHE_DIR / CIK / TARGET_ACCESSION

TARGET_INSTANCE = TARGET_FILING_DIR / "apld-20260531_htm.xml"
TARGET_CAL = TARGET_FILING_DIR / "apld-20260531_cal.xml"
TARGET_PRE = TARGET_FILING_DIR / "apld-20260531_pre.xml"
TARGET_DEF = TARGET_FILING_DIR / "apld-20260531_def.xml"
TARGET_LAB = TARGET_FILING_DIR / "apld-20260531_lab.xml"

# Keywords used to find "debt-related" concepts (case-insensitive)
DEBT_KEYWORDS = ("debt", "loan", "note", "borrow", "financing", "obligation")

# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------

# Clark-notation namespaces (namespace URIs are stable; prefixes are not)
NS_LINK = "http://www.xbrl.org/2003/linkbase"
NS_XLINK = "http://www.w3.org/1999/xlink"
NS_INSTANCE = "http://www.xbrl.org/2003/instance"

CLARK_LINK = f"{{{NS_LINK}}}"
CLARK_XLINK = f"{{{NS_XLINK}}}"
CLARK_INSTANCE = f"{{{NS_INSTANCE}}}"

# Attribute names in Clark notation
ATTR_LABEL = f"{CLARK_XLINK}label"
ATTR_HREF = f"{CLARK_XLINK}href"
ATTR_FROM = f"{CLARK_XLINK}from"
ATTR_TO = f"{CLARK_XLINK}to"
ATTR_ROLE = f"{CLARK_XLINK}role"
ATTR_TYPE = f"{CLARK_XLINK}type"


class InspectionError(Exception):
    """Raised when a file is missing, malformed, or unusable."""


def load_xml(path: Path | str) -> ET.Element:
    """
    Parse an XML file and return its root element.

    Raises InspectionError with a clear message on failure so callers can
    print a friendly error and exit gracefully.
    """
    path = Path(path)
    if not path.exists():
        raise InspectionError(f"File not found: {path}")
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise InspectionError(f"Malformed XML in {path.name}: {exc}") from exc
    return tree.getroot()


def read_raw(path: Path | str) -> str:
    """Read a file's raw text (used for namespace declaration scanning)."""
    path = Path(path)
    if not path.exists():
        raise InspectionError(f"File not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InspectionError(f"Cannot read {path.name}: {exc}") from exc


def iter_children_by_tag(root: ET.Element, tag_local: str) -> list[ET.Element]:
    """Return direct children of `root` whose local tag name is `tag_local`."""
    return [el for el in root if el.tag == f"{CLARK_LINK}{tag_local}"]


# ---------------------------------------------------------------------------
# Concept-name handling
# ---------------------------------------------------------------------------

_QNAME_SPLIT_RE = re.compile(r"^([^:]+):(.+)$")


def split_qname(tag: str) -> tuple[str, str]:
    """
    Split a Clark-notation tag ``{uri}LocalName`` or a raw QName
    ``prefix:LocalName`` into (prefix, local_name).

    For Clark tags the prefix is resolved to a readable alias when possible.
    """
    if tag.startswith("{"):
        uri, local = tag[1:].split("}", 1)
        return uri, local
    match = _QNAME_SPLIT_RE.match(tag)
    if match:
        return match.group(1), match.group(2)
    return "", tag


def concept_from_href(href: str) -> tuple[str, str]:
    """
    Extract (prefix, concept_name) from a locator href fragment.

    Linkbase locators use hrefs like::

        https://xbrl.fasb.org/us-gaap/2026/elts/us-gaap-2026.xsd#us-gaap_Liabilities
        apld-20260531.xsd#apld_CustomerDepositsCurrent1

    The fragment is ``<prefix>_<concept>`` -- note the UNDERSCORE, not a
    colon.  Prefixes are taken from the fragment; the concept name is the
    remainder after the FIRST underscore (concept names can themselves
    contain underscores, e.g. ``dei_DocumentType``).
    """
    if "#" in href:
        fragment = href.split("#", 1)[1]
    else:
        fragment = href
    fragment = fragment.strip()
    if "_" in fragment:
        prefix, _, name = fragment.partition("_")
        return prefix, name
    return "", fragment


# ---------------------------------------------------------------------------
# Namespace extraction
# ---------------------------------------------------------------------------

_XMLNS_RE = re.compile(r'xmlns(?:[:]([\w.-]+))?="([^"]+)"')


def extract_namespaces(raw: str) -> dict[str, str]:
    """
    Extract prefix -> URI mappings from xmlns declarations in raw XML text.

    Returns a dict keyed by prefix ('' for the default namespace).
    ElementTree strips prefix info, so we scan the raw text -- all xmlns
    declarations live on the root element, which appears before any content
    that could contain a false match.
    """
    ns_map: dict[str, str] = {}
    # Only scan the root element (first '<...>' tag) to avoid picking up
    # xmlns declarations inside nested elements or text.
    for match in _XMLNS_RE.finditer(raw):
        prefix = match.group(1) or ""
        uri = match.group(2)
        if prefix not in ns_map:
            ns_map[prefix] = uri
    return ns_map


def namespace_class(uri: str) -> str:
    """
    Classify a namespace URI as 'standard' or 'company'.

    Standard = FASB (us-gaap, srt) and SEC (dei, cyd, ecd, stpr) taxonomies
    plus the XBRL infrastructure namespaces.  Anything else (in practice, the
    registrant's own namespace like http://appliedblockchaininc.com/...) is
    'company'.
    """
    if not uri:
        return "unknown"
    if (
        "fasb.org" in uri
        or "xbrl.sec.gov" in uri
        or uri.startswith("http://www.xbrl.org")
        or uri.startswith("http://xbrl.org")
        or "w3.org" in uri
        or "xbrldi" in uri
        or "iso4217" in uri
    ):
        return "standard"
    return "company"


def is_debt_concept(concept_name: str) -> bool:
    """True if the concept local name contains any debt keyword (lowercased)."""
    lowered = concept_name.lower()
    return any(kw in lowered for kw in DEBT_KEYWORDS)


def pretty_namespace(prefix: str, uri: str) -> str:
    """Human label for a namespace, e.g. 'us-gaap (standard)'."""
    cls = namespace_class(uri)
    if cls == "standard":
        note = ""
        if "us-gaap" in uri:
            note = "  <-- GAAP taxonomy"
        elif "dei" in uri:
            note = "  <-- SEC document & entity info"
        elif "srt" in uri:
            note = "  <-- SEC statement reporting types"
        return f"{prefix or '(default)':<10} -> {uri}  [standard]{note}"
    return f"{prefix or '(default)':<10} -> {uri}  [COMPANY - registrant-invented]"


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def ensure_notes_dir() -> Path:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    return NOTES_DIR


def emit_report(filename: str, title: str, body: str, *, echo: bool = True) -> Path:
    """
    Write `body` to notes/inspection/<filename> and optionally echo it
    to stdout.  Returns the written file path.
    """
    out_dir = ensure_notes_dir()
    out_path = out_dir / filename
    header = (
        f"{'=' * 78}\n"
        f" {title}\n"
        f" Generated: {out_path}\n"
        f"{'=' * 78}\n"
    )
    full = header + body
    if not full.endswith("\n"):
        full += "\n"
    out_path.write_text(full, encoding="utf-8")
    if echo:
        print(full)
    return out_path


def banner(text: str, char: str = "=", width: int = 78) -> str:
    return f"\n{char * width}\n{text}\n{char * width}\n"


def pretty_arc_table(rows: list[tuple[str, str, str, str, str, str]]) -> str:
    """
    Format arc rows as a fixed-width table.

    Columns: parent, child, weight, order, parent type, child type.
    """
    if not rows:
        return "  (no matching arcs)\n"

    headers = ["Parent concept", "Child concept", "Weight", "Order",
               "Parent type", "Child type"]

    # Dynamic column widths: fit the longest value, capped so very long
    # concept names don't explode the table.
    col_max = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_max[i] = max(col_max[i], len(cell))
    widths = [min(w, 52) for w in col_max]

    def fmt_cell(text: str, width: int) -> str:
        if len(text) > width:
            return text[: width - 1].ljust(width)
        return text.ljust(width)

    sep = "  "  # two-space gap between columns
    lines = []
    lines.append("  " + sep.join(fmt_cell(h, w) for h, w in zip(headers, widths)))
    lines.append("  " + "-" * (sum(widths) + len(sep) * (len(widths) - 1)))
    for parent, child, weight, order, ptype, ctype in rows:
        lines.append(
            "  "
            + sep.join(
                fmt_cell(cell, width)
                for cell, width in zip(
                    (parent, child, weight, order, ptype, ctype), widths
                )
            )
        )
    return "\n".join(lines)


def format_exception(exc: Exception) -> str:
    return f"ERROR: {exc}"


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def default_instance_path() -> Path:
    return TARGET_INSTANCE


def default_cal_path() -> Path:
    return TARGET_CAL


def default_pre_path() -> Path:
    return TARGET_PRE
