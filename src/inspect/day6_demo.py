
"""
taxonomy_extraction.py

SchemaRef extraction, standard taxonomy bootstrap,
and dimension extraction on APLD's FY2025 10-K.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from arelle import Cntlr
from schema_ref_extractor import extract_taxonomy_info
from standard_taxonomy_bootstrap import StandardTaxonomyBootstrap, print_seed_list
from dimension_extractor import DimensionExtractor, print_dimensions

FILING = "0001144879-25-000021"
CIK = "0001144879"
CACHE_DIR = Path("cache")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main():
    filing_dir = CACHE_DIR / CIK / FILING
    # Load the XBRL instance document (has facts/contexts)
    # The _htm.xml file is the actual instance; schema refs inside it resolve the DTS
    instance_files = list(filing_dir.glob("*_htm.xml"))
    if not instance_files:
        # Fallback to any .xml that isn't a linkbase
        instance_files = [f for f in filing_dir.glob("*.xml")
                          if not any(f.name.endswith(s) for s in ("_pre.xml", "_cal.xml", "_def.xml", "_lab.xml"))]
    if not instance_files:
        print(f"ERROR: No instance document in {filing_dir}")
        return 1

    entry_point = instance_files[0]
    print(f"Loading: {entry_point.name}")

    cntlr = Cntlr.Cntlr(hasGui=False)
    cntlr.startLogging(logFileName="logToPrint", logLevel="WARNING")
    
    try:
        model = cntlr.modelManager.load(str(entry_point))
        if model is None or model.modelDocument is None:
            print("ERROR: Load failed")
            return 1

        # ── 1. SchemaRef / Taxonomy Year ───────────────────────────────────
        print(f"\n{'='*60}")
        print("SCHEMA REFS & TAXONOMY YEAR")
        print(f"{'='*60}")
        
        tax_info = extract_taxonomy_info(model)
        print(f"US-GAAP Year: {tax_info.us_gaap_year or 'NOT DETECTED'}")
        print(f"US-GAAP URI: {tax_info.us_gaap_uri or 'N/A'}")
        print(f"\nAll schema refs ({len(tax_info.schema_refs)}):")
        for ref in tax_info.schema_refs[:5]:  # Show first 5
            print(f"  {ref}")
        if len(tax_info.schema_refs) > 5:
            print(f"  ... and {len(tax_info.schema_refs) - 5} more")

        # ── 2. Standard Debt Concept Seed List ─────────────────────────────
        print(f"\n{'='*60}")
        print("STANDARD TAXONOMY BOOTSTRAP")
        print(f"{'='*60}")
        
        bootstrap = StandardTaxonomyBootstrap(model)
        seed = bootstrap.build_seed_list()
        print_seed_list(seed)

        # Save seed list as JSON
        import json
        seed_path = filing_dir / "standard_debt_seed.json"
        with open(seed_path, "w", encoding="utf-8") as f:
            json.dump([{"name": s.name, "is_total": s.is_total, "is_component": s.is_component} for s in seed], f, indent=2)
        print(f"[Saved: {seed_path}]")

        # ── 3. Dimension Extraction ────────────────────────────────────────
        print(f"\n{'='*60}")
        print("DIMENSIONAL STRUCTURES")
        print(f"{'='*60}")
        
        dim_ext = DimensionExtractor(model)
        axes = dim_ext.find_debt_axes()
        print_dimensions(axes)

        # Fact-by-dimension inspection
        print(f"\n{'='*60}")
        print("DEBT FACTS WITH DIMENSIONS")
        print(f"{'='*60}")
        
        fact_dims = dim_ext.find_debt_facts_by_dimension()
        for concept_name, dims in sorted(fact_dims.items())[:10]:
            print(f"{concept_name}")
            for d in set(dims):
                print(f"  → {d}")

    finally:
        cntlr.modelManager.close()
        cntlr.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())