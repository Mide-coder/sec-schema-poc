"""Demonstrates calculation tree extraction from APLD FY2025 10-K filing."""

import json
import sys
from pathlib import Path

from arelle import Cntlr

from calc_tree import CalcTreeExtractor, print_calc_tree, tree_to_dict
from config import CACHE_DIR, CIK

FILING = "0001144879-25-000021"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main():
    filing_dir = CACHE_DIR / CIK / FILING
    xsd_files = list(filing_dir.glob("*.xsd"))
    if not xsd_files:
        print(f"ERROR: No .xsd in {filing_dir}")
        return 1

    entry_point = xsd_files[0]
    print(f"Loading: {entry_point.name}")

    cntlr = Cntlr.Cntlr(hasGui=False)
    cntlr.startLogging(logFileName="logToPrint", logLevel="WARNING")
    
    try:
        model = cntlr.modelManager.load(str(entry_point))
        if model is None or model.modelDocument is None:
            print("ERROR: Load failed")
            return 1

        extractor = CalcTreeExtractor(model)

        # Auto-discover debt roots
        print(f"\n{'='*70}")
        print("AUTO-DISCOVERED DEBT CALCULATION ROOTS")
        print(f"{'='*70}")
        
        roots = extractor.find_debt_roots()
        print(f"Found {len(roots)} debt-related calc parents\n")

        for root in roots:
            tree = extractor.build_tree(root)
            if tree:
                print_calc_tree(tree)
                print()

        # Cross-check against known values
        print(f"{'='*70}")
        print("DAY 3 CROSS-CHECK: LongTermDebt")
        print(f"{'='*70}")
        
        ltd = extractor.find_concept_by_name("LongTermDebt")
        # NOTE: never truth-test an Arelle concept — it's an lxml element and
        # bool(childless element) is False. Always use `is not None`.
        if ltd is not None:
            tree = extractor.build_tree(ltd)
            if tree:
                print_calc_tree(tree)
                json_path = filing_dir / "calc_tree_longtermdebt.json"
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(tree_to_dict(tree), f, indent=2)
                print(f"\n[Saved: {json_path}]")

        # FY2025 Notes Payable
        print(f"\n{'='*70}")
        print("NOTES PAYABLE TREE (FY2025 multi-instrument)")
        print(f"{'='*70}")
        
        notes = extractor.find_concept_by_name("LongTermNotesPayable")
        if notes is not None:
            tree = extractor.build_tree(notes)
            if tree:
                print_calc_tree(tree)
                json_path = filing_dir / "calc_tree_notespayable.json"
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(tree_to_dict(tree), f, indent=2)
                print(f"\n[Saved: {json_path}]")

    finally:
        cntlr.modelManager.close()
        cntlr.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())