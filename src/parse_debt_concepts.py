
"""
parse_debt_concepts.py

 Load one APLD filing with Arelle and extract debt-related concepts.
Designed for reuse in Day 5+ pipeline.
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

#  Arelle imports 
try:
    from arelle import Cntlr, ModelXbrl, XbrlConst
    ARELLE_AVAILABLE = True
except ImportError:
    ARELLE_AVAILABLE = False
    raise RuntimeError("Arelle not installed. Run: pip install arelle-release")

# Windows consoles default to cp1252, which can't encode ✓ (U+2713) etc.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

#  Logging 
# Arelle is chatty. We suppress its internal logging after capturing errors.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


#  Data model 

@dataclass(frozen=True, slots=True)
class DebtConcept:
    """
    Immutable record for a single debt-related concept.
    Frozen + slots = lightweight, hashable, memory-efficient.
    """
    name: str
    namespace_uri: str
    namespace_type: str  # "STANDARD" | "COMPANY" | "OTHER"
    label: str | None


#  Configuration 

DEBT_KEYWORDS = frozenset(
    ["debt", "loan", "note", "borrow", "financing", "obligation"]
)

STANDARD_URIS = frozenset([
    "fasb.org",
    "xbrl.org",
    "sec.gov",
    "w3.org",
])

COMPANY_URIS = frozenset([
    "apld",
    "applieddigital",
    "appliedblockchaininc",
])


#  Extractor class (reusable for Day 5+) 

class DebtConceptExtractor:
    """
    Encapsulates Arelle lifecycle and debt-concept extraction.
    
    Design rationale:
    - Context manager ensures Arelle models are unloaded even on exceptions
    - Extraction is pure (no side effects) — pass in model, get concepts out
    - Can be reused across multiple filings in a loop
    """

    def __init__(self):
        # hasGui=False prevents Arelle from trying to initialize Qt/GTK
        self.cntlr = Cntlr.Cntlr(hasGui=False)
        # Arelle only initializes its logger via startLogging(); surface
        # WARNING+ only — we use Python's own logger for the rest.
        self.cntlr.startLogging(logFileName="logToPrint", logLevel="WARNING")

    def load_filing(self, entry_point: Path) -> ModelXbrl.ModelXbrl:
        """
        Load a taxonomy entry point and validate it actually parsed.
        
        Raises:
            RuntimeError: if Arelle fails to load or produces critical errors.
        """
        logger.info("Loading taxonomy: %s", entry_point)
        model_xbrl = self.cntlr.modelManager.load(str(entry_point))

        if model_xbrl is None or model_xbrl.modelDocument is None:
            raise RuntimeError(
                f"Arelle failed to load {entry_point}. "
                "Check the .xsd file exists and is valid."
            )

        # Arelle collects validation errors during load
        if getattr(model_xbrl, "errors", None):
            error_count = len(model_xbrl.errors)
            logger.warning(
                "Arelle reported %d validation errors — proceeding with caution",
                error_count
            )
            for err in model_xbrl.errors[:3]:  # Log first 3 only
                logger.warning("  Arelle error: %s", err)

        logger.info(
            "Loaded. Model document: %s | Concepts: %d",
            model_xbrl.modelDocument.basename,
            len(model_xbrl.qnameConcepts),
        )
        return model_xbrl

    def extract_debt_concepts(
        self,
        model_xbrl: ModelXbrl.ModelXbrl,
    ) -> list[DebtConcept]:
        """
        Pure extraction: walk every concept, filter for debt keywords,
        classify namespace, fetch label. No printing, no side effects.
        """
        concepts: list[DebtConcept] = []
        label_rel_set = model_xbrl.relationshipSet(
            "http://www.xbrl.org/2003/arcrole/concept-label"
        )

        for qname_obj, concept in model_xbrl.qnameConcepts.items():
            name = str(qname_obj.localName)
            ns_uri = str(qname_obj.namespaceURI)

            # Fetch label via Arelle's relationship set.
            # NOTE: label() signature is label(modelFrom, role, lang, ...)
            label = None
            if label_rel_set:
                try:
                    label = label_rel_set.label(
                        concept,
                        role=XbrlConst.standardLabel,
                        lang="en-US",
                    )
                except Exception:
                    pass  # Labels are optional; don't fail extraction

            if not self._is_debt_related(name, label):
                continue

            concepts.append(DebtConcept(
                name=name,
                namespace_uri=ns_uri,
                namespace_type=self._classify_namespace(ns_uri),
                label=label,
            ))

        # Sort: COMPANY first, then alphabetically
        concepts.sort(
            key=lambda c: (0 if c.namespace_type == "COMPANY" else 1, c.name)
        )
        return concepts

    @staticmethod
    def _is_debt_related(name: str, label: str | None) -> bool:
        text = f"{name} {label or ''}".lower()
        return any(kw in text for kw in DEBT_KEYWORDS)

    @staticmethod
    def _classify_namespace(uri: str) -> str:
        uri_lower = uri.lower()
        if any(s in uri_lower for s in STANDARD_URIS):
            return "STANDARD"
        if any(s in uri_lower for s in COMPANY_URIS):
            return "COMPANY"
        return "OTHER"

    def close(self) -> None:
        """Unload all models and shutdown Arelle cleanly."""
        if self.cntlr.modelManager:
            self.cntlr.modelManager.close()
        self.cntlr.close()
        logger.debug("Arelle shutdown complete")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


#  Presentation (separated from extraction) 

def print_concepts_table(concepts: list[DebtConcept], filing_name: str) -> None:
    print(f"\n{'='*75}")
    print(f"DEBT-RELATED CONCEPTS IN {filing_name}")
    print(f"{'='*75}")
    print(f"{'Name':<45} {'Type':<10} {'Label'}")
    print("-" * 75)

    for c in concepts:
        label = (c.label or "(no label)")
        label = label[:55] + "..." if len(label) > 55 else label
        print(f"{c.name:<45} {c.namespace_type:<10} {label}")

    total = len(concepts)
    company = sum(1 for c in concepts if c.namespace_type == "COMPANY")
    standard = sum(1 for c in concepts if c.namespace_type == "STANDARD")
    print(f"\nTotal: {total} | COMPANY: {company} | STANDARD: {standard}")


def cross_check_day3(concepts: list[DebtConcept]) -> None:
    """
    Verify key concepts from manual Day 3 trace appear in Arelle output.
    """
    print(f"\n{'='*75}")
    print("DAY 3 CROSS-CHECK")
    print(f"{'='*75}")

    key_names = ["LongTermDebt", "LongTermNotesPayable", "DebtInstrumentLineItems"]
    name_map = {c.name: c for c in concepts}

    for key in key_names:
        if key in name_map:
            c = name_map[key]
            print(f"  ✓ {c.name} ({c.namespace_type})")
        else:
            print(f"  ✗ {key} — NOT FOUND")

    # Also check for the $4.96B concept from Day 3 (exact name preferred)
    notes = [c for c in concepts if c.name == "LongTermNotesPayable"]
    if not notes:
        notes = [c for c in concepts if "LongTermNotesPayable" in c.name]
    if notes:
        print(f"\n  Day 3 value check: {notes[0].name} found with label '{notes[0].label}'")


#  Main 

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract debt-related XBRL concepts from an APLD filing."
    )
    parser.add_argument(
        "--filing",
        default="0001144879-26-000048",
        help="Accession number of filing to analyze (default: latest 10-K)",
    )
    args = parser.parse_args()

    cache_dir = Path("cache")
    cik = "0001144879"
    entry_point = cache_dir / cik / args.filing / "apld-20260531.xsd"

    if not entry_point.exists():
        # Try to auto-detect the .xsd filename (varies by filing date)
        filing_dir = cache_dir / cik / args.filing
        if filing_dir.exists():
            xsd_files = list(filing_dir.glob("*.xsd"))
            if xsd_files:
                entry_point = xsd_files[0]
                logger.info("Auto-detected entry point: %s", entry_point.name)

    if not entry_point.exists():
        logger.error("Entry point not found: %s", entry_point)
        return 1

    try:
        with DebtConceptExtractor() as extractor:
            model = extractor.load_filing(entry_point)
            concepts = extractor.extract_debt_concepts(model)
            print_concepts_table(concepts, args.filing)
            cross_check_day3(concepts)
    except RuntimeError as e:
        logger.error("Failed to process filing: %s", e)
        return 1
    except Exception:
        logger.exception("Unexpected error")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())