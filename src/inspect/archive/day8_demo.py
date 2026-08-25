"""Demonstrates diff engine classification of APLD first 10-Q against v0."""

import sys
from pathlib import Path

from arelle import Cntlr

from config import CACHE_DIR, CIK, SCHEMA_DIR
from schema.diff_engine import DiffEngine
from schema.graph import SchemaGraph
from schema.schema_types import SchemaVersion
from schema.version_store import SchemaStore

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def load_filing(accession: str):
    filing_dir = CACHE_DIR / CIK / accession
    xsd_files = list(filing_dir.glob("*_htm.xml"))
    if not xsd_files:
        xsd_files = list(filing_dir.glob("*.xsd"))
    if not xsd_files:
        return None, None

    cntlr = Cntlr.Cntlr(hasGui=False)
    cntlr.startLogging(logFileName="logToPrint", logLevel="WARNING")
    model = cntlr.modelManager.load(str(xsd_files[0]))
    return cntlr, model


def main():
    store = SchemaStore(SCHEMA_DIR)
    v0 = store.get_version("v0")
    if v0 is None:
        print("ERROR: v0 not found")
        return 1

    print(f"{'='*70}")
    print("DIFF ENGINE DEMO")
    print(f"{'='*70}")
    print(f"Baseline: {v0.version_id} ({len(v0.concepts)} concepts)")

    # Test filing: FY2025 10-K (rich with company extensions)
    accession = "0001144879-25-000021"
    cntlr, model = load_filing(accession)
    if model is None:
        print(f"ERROR: Could not load {accession}")
        return 1

    try:
        engine = DiffEngine(v0)
        result = engine.diff_filing(model, accession)

        print(f"\nFiling: {accession}")
        print(f"Prior version: {result.prior_version_id}")
        print(f"Classifications: {len(result.classifications)}")

        # Group by classification
        groups = {}
        for c in result.classifications:
            groups.setdefault(c.classification, []).append(c)

        for classification, items in sorted(groups.items()):
            print(f"\n--- {classification} ({len(items)}) ---")
            for item in items[:5]:  # Show first 5
                match = f" -> {item.matched_concept}" if item.matched_concept else ""
                print(f"  {item.concept_name:<40} {item.evidence[:50]}{match}")
            if len(items) > 5:
                print(f"  ... and {len(items) - 5} more")

        print(f"\nNew calc arcs: {len(result.new_calc_arcs)}")
        print(f"New dimension arcs: {len(result.new_dimension_arcs)}")

        # Ambiguous concept test
        print(f"\n{'='*70}")
        print("AMBIGUOUS CONCEPT TEST")
        print(f"{'='*70}")
        
        # Construct a fake ambiguous concept by renaming a real one
        fake_name = "ZZZUnknownFinancingItem"
        fake = engine._classify(
            fake_name, "COMPANY", None, None, None
        )
        print(f"Fake concept: {fake.concept_name}")
        print(f"Classification: {fake.classification}")
        if fake.classification == "NEW_EXTENSION_UNRESOLVED":
            print("PASS: Ambiguous concept correctly left unresolved")
        else:
            print(f"FAIL: Expected UNRESOLVED, got {fake.classification}")
            return 1

    finally:
        cntlr.modelManager.close()
        cntlr.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())