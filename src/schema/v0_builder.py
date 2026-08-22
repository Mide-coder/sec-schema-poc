
"""
v0_builder.py

 Build SchemaVersion v0 from the standard US-GAAP debt taxonomy.
This is the immutable baseline before any company extensions are added.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from arelle import Cntlr
from schema.schema_types import Concept, CalcArc, DimensionArc, SchemaVersion
from schema.graph import SchemaGraph
from standard_taxonomy_bootstrap import StandardTaxonomyBootstrap
from dimension_extractor import DimensionExtractor
from schema_ref_extractor import extract_taxonomy_info


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CACHE_DIR = Path("cache")
CIK = "0001144879"
SCHEMA_VERSIONS_DIR = Path("schema_versions")


def build_v0_from_filing(accession: str) -> SchemaVersion | None:
    """
    Load a filing's DTS, extract standard debt concepts + dimensions,
    and freeze as SchemaVersion v0.
    """
    filing_dir = CACHE_DIR / CIK / accession
    xsd_files = list(filing_dir.glob("*.xsd"))
    if not xsd_files:
        # Fallback to instance document
        xsd_files = list(filing_dir.glob("*_htm.xml"))
    
    if not xsd_files:
        logger.error("No entry point found for %s", accession)
        return None

    entry_point = xsd_files[0]
    logger.info("Building v0 from: %s", entry_point.name)

    cntlr = Cntlr.Cntlr(hasGui=False)
    cntlr.startLogging(logFileName="logToPrint", logLevel="WARNING")

    try:
        model = cntlr.modelManager.load(str(entry_point))
        if model is None or model.modelDocument is None:
            logger.error("[%s] Arelle failed to load entry point %s", accession, entry_point.name)
            return None

        # Detect taxonomy year
        tax_info = extract_taxonomy_info(model)
        logger.info(
            "[%s] US-GAAP taxonomy year: %s",
            accession, tax_info.us_gaap_year,
        )

        # Build graph
        graph = SchemaGraph()

        # 1. Add standard debt concepts from calc tree walk
        bootstrap = StandardTaxonomyBootstrap(model)
        seed_concepts = bootstrap.build_seed_list()

        for seed in seed_concepts:
            graph.add_concept(Concept(
                name=seed.name,
                namespace_uri=seed.namespace_uri,
                namespace_type=seed.namespace_type,
                label=seed.label,
                is_total=seed.is_total,
                is_component=seed.is_component,
            ))

        # 2. Add ALL calc arcs where BOTH parent and child are standard concepts
        if bootstrap.calc_rel_set:
            arc_count = 0
            for rel in bootstrap.calc_rel_set.modelRelationships:
                parent = rel.fromModelObject
                child = rel.toModelObject
                if parent is None or child is None:
                    continue
                if not bootstrap.is_standard_concept(parent):
                    continue
                if not bootstrap.is_standard_concept(child):
                    continue

                graph.add_calc_arc(CalcArc(
                    parent_name=str(parent.qname.localName),
                    child_name=str(child.qname.localName),
                    weight=getattr(rel, "weight", 1.0),
                    order=getattr(rel, "order", 0.0),
                ))
                arc_count += 1
            logger.info("Extracted %d standard-standard calc arcs", arc_count)

        # 3. Add standard dimension arcs (only standard axes/members)
        dim_ext = DimensionExtractor(model)
        axes = dim_ext.find_debt_axes()
        for axis in axes:
            if axis.namespace_type != "STANDARD":
                continue
            for member in axis.members:
                if member.namespace_type == "STANDARD":
                    graph.add_dimension_arc(DimensionArc(
                        axis_name=axis.name,
                        member_name=member.name,
                        member_namespace_type=member.namespace_type,
                    ))

        # 4. Freeze to SchemaVersion v0
        v0 = graph.to_version(
            version_id="v0",
            parent_version_id=None,
            source_filing=None,  # v0 comes from standard taxonomy, not a filing
            taxonomy_year=tax_info.us_gaap_year,
        )

        logger.info(
            "v0 built: %d concepts, %d calc arcs, %d dimension arcs, hash=%s",
            len(v0.concepts), len(v0.calc_arcs), len(v0.dimension_arcs), v0.content_hash
        )
        return v0

    finally:
        cntlr.modelManager.close()
        cntlr.close()


def save_version(version: SchemaVersion, directory: Path) -> Path:
    """Serialize SchemaVersion to JSON."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{version.version_id}.json"

    # Convert dataclass to dict
    data = {
        "version_id": version.version_id,
        "parent_version_id": version.parent_version_id,
        "source_filing": version.source_filing,
        "taxonomy_year": version.taxonomy_year,
        "content_hash": version.content_hash,
        "concepts": [
            {
                "name": c.name,
                "namespace_uri": c.namespace_uri,
                "namespace_type": c.namespace_type,
                "label": c.label,
                "is_total": c.is_total,
                "is_component": c.is_component,
            }
            for c in version.concepts
        ],
        "calc_arcs": [
            {"parent": a.parent_name, "child": a.child_name, "weight": a.weight, "order": a.order}
            for a in version.calc_arcs
        ],
        "dimension_arcs": [
            {"axis": a.axis_name, "member": a.member_name, "member_ns": a.member_namespace_type}
            for a in version.dimension_arcs
        ],
        "unresolved": [
            {"name": c.name, "namespace_type": c.namespace_type}
            for c in version.unresolved
        ],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)

    logger.info("Saved: %s", path)
    return path


def load_version(path: Path) -> SchemaVersion:
    """Deserialize SchemaVersion from JSON."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    return SchemaVersion(
        version_id=data["version_id"],
        parent_version_id=data.get("parent_version_id"),
        source_filing=data.get("source_filing"),
        taxonomy_year=data.get("taxonomy_year"),
        content_hash=data.get("content_hash", ""),
        concepts=tuple(
            Concept(
                name=c["name"],
                namespace_uri=c["namespace_uri"],
                namespace_type=c["namespace_type"],
                label=c.get("label"),
                is_total=c.get("is_total", False),
                is_component=c.get("is_component", False),
            )
            for c in data["concepts"]
        ),
        calc_arcs=tuple(
            CalcArc(
                parent_name=a["parent"],
                child_name=a["child"],
                weight=a["weight"],
                order=a["order"],
            )
            for a in data["calc_arcs"]
        ),
        dimension_arcs=tuple(
            DimensionArc(
                axis_name=a["axis"],
                member_name=a["member"],
                member_namespace_type=a["member_ns"],
            )
            for a in data["dimension_arcs"]
        ),
        unresolved=tuple(
            Concept(
                name=c["name"],
                namespace_uri="",
                namespace_type=c["namespace_type"],
                label=None,
            )
            for c in data.get("unresolved", [])
        ),
    )


def round_trip_test(version: SchemaVersion, directory: Path) -> bool:
    """
    Save → load → re-save → compare byte-for-byte.
    Proves serialization is lossless.
    """
    path1 = save_version(version, directory)
    loaded = load_version(path1)
    path2 = save_version(loaded, directory / "roundtrip")

    with open(path1, "rb") as f:
        bytes1 = f.read()
    with open(path2, "rb") as f:
        bytes2 = f.read()

    if bytes1 == bytes2:
        logger.info("ROUND-TRIP PASS: %s == %s", path1.name, path2.name)
        return True
    else:
        logger.error("ROUND-TRIP FAIL: serialization is lossy")
        return False


def main() -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    # Build v0 from FY2025 10-K (has rich standard taxonomy loaded)
    v0 = build_v0_from_filing("0001144879-25-000021")
    if v0 is None:
        return 1

    # Save
    SCHEMA_VERSIONS_DIR.mkdir(exist_ok=True)
    save_version(v0, SCHEMA_VERSIONS_DIR)

    # Round-trip test
    if not round_trip_test(v0, SCHEMA_VERSIONS_DIR):
        return 1

    # Print summary
    print(f"\n{'='*60}")
    print("SCHEMA v0 SUMMARY")
    print(f"{'='*60}")
    print(f"Version ID:     {v0.version_id}")
    print(f"Taxonomy Year:  {v0.taxonomy_year}")
    print(f"Content Hash:   {v0.content_hash}")
    print(f"Concepts:       {len(v0.concepts)}")
    print(f"  STANDARD:     {sum(1 for c in v0.concepts if c.namespace_type == 'STANDARD')}")
    print(f"  COMPANY:      {sum(1 for c in v0.concepts if c.namespace_type == 'COMPANY')}")
    print(f"Calc Arcs:      {len(v0.calc_arcs)}")
    print(f"Dimension Arcs: {len(v0.dimension_arcs)}")
    print(f"Unresolved:     {len(v0.unresolved)}")

    # Show first 10 concepts
    print(f"\nFirst 10 concepts:")
    for c in v0.concepts[:10]:
        total = "TOTAL" if c.is_total else ""
        comp = "COMP" if c.is_component else ""
        flags = f"{total}/{comp}".strip("/")
        print(f"  {c.name:<40} {c.namespace_type:<10} {flags}")

    return 0


if __name__ == "__main__":
    sys.exit(main())