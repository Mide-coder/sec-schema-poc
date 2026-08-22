#!/usr/bin/env python3
"""
process_filing.py

Day 9: End-to-end pipeline for a single filing.
download (if needed) -> parse -> diff -> create version (or no-op)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from arelle import Cntlr
from downloader import SECDownloader
from rate_limiter import RateLimiter
from schema.version_store import SchemaStore
from schema.diff_engine import DiffEngine
from schema.graph import SchemaGraph
from schema.schema_types import SchemaVersion, Concept, CalcArc, DimensionArc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CACHE_DIR = Path("cache")
SCHEMA_DIR = Path("schema_versions")
USER_AGENT = "Mide-project adegboyeayomide822@gmail.com"


def ensure_filing_cached(cik: str, accession: str) -> bool:
    """Download filing if not already in cache."""
    filing_dir = CACHE_DIR / cik / accession
    if filing_dir.exists() and any(filing_dir.iterdir()):
        logger.info("Cache hit: %s", accession)
        return True

    logger.info("Downloading: %s", accession)
    limiter = RateLimiter()
    downloader = SECDownloader(cik, CACHE_DIR, USER_AGENT, limiter)
    try:
        files = downloader.download_filing_xbrl(accession)
        logger.info("Downloaded %d files", len(files))
        return True
    except Exception:
        logger.exception("Download failed for %s", accession)
        return False


def load_filing_model(accession: str):
    """Load cached filing into Arelle."""
    cik = "0001144879"
    filing_dir = CACHE_DIR / cik / accession

    # Prefer instance document (has facts/contexts)
    entry_points = list(filing_dir.glob("*_htm.xml"))
    if not entry_points:
        entry_points = list(filing_dir.glob("*.xsd"))
    if not entry_points:
        logger.error("No entry point for %s", accession)
        return None, None

    cntlr = Cntlr.Cntlr(hasGui=False)
    cntlr.startLogging(logFileName="logToPrint", logLevel="WARNING")

    try:
        model = cntlr.modelManager.load(str(entry_points[0]))
        if model is None or model.modelDocument is None:
            logger.error("Arelle failed to load %s", accession)
            cntlr.modelManager.close()
            cntlr.close()
            return None, None
        return cntlr, model
    except Exception:
        logger.exception("Load failed for %s", accession)
        cntlr.modelManager.close()
        cntlr.close()
        return None, None


def process_filing(cik: str, accession: str) -> SchemaVersion | None:
    """
    Process one filing end-to-end.

    Returns:
        SchemaVersion used for this filing (new or existing)
    """
    # 1. Ensure cached
    if not ensure_filing_cached(cik, accession):
        return None

    # 2. Load into Arelle
    cntlr, model = load_filing_model(accession)
    if model is None:
        return None

    try:
        # 3. Get current schema
        store = SchemaStore(SCHEMA_DIR)
        current = store.get_version(store._latest_version_id() or "v0")
        if current is None:
            logger.error("No schema baseline found")
            return None

        # 4. Diff
        engine = DiffEngine(current)
        diff_result = engine.diff_filing(model, accession)

        # 5. Collect unresolved concepts for the version
        unresolved_concepts = []
        for classification in diff_result.classifications:
            if classification.classification == "NEW_EXTENSION_UNRESOLVED":
                # Re-extract the concept from the model
                for qname_obj, concept in model.qnameConcepts.items():
                    if str(qname_obj.localName) == classification.concept_name:
                        unresolved_concepts.append(Concept(
                            name=classification.concept_name,
                            namespace_uri=str(qname_obj.namespaceURI),
                            namespace_type=classification.namespace_type,
                            label=None,
                        ))
                        break
        logger.info("Collected %d unresolved concepts", len(unresolved_concepts))

        # 6. Build new graph if there are new concepts or arcs
        has_changes = (
            len(diff_result.new_concepts) > 0
            or len(diff_result.new_calc_arcs) > 0
            or len(diff_result.new_dimension_arcs) > 0
        )

        if not has_changes:
            logger.info("No changes detected for %s — no-op", accession)
            # Return current version (no new version created)
            return current

        # 7. Merge changes into new graph
        graph = SchemaGraph.from_version(current)
        for concept in diff_result.new_concepts:
            graph.add_concept(concept)
        for arc in diff_result.new_calc_arcs:
            graph.add_calc_arc(arc)
        for arc in diff_result.new_dimension_arcs:
            graph.add_dimension_arc(arc)

        # 8. Create new version
        new_version = store.create_version(
            graph=graph,
            source_filing=accession,
            taxonomy_year=current.taxonomy_year,  # Inherit from prior
            unresolved=tuple(unresolved_concepts),
        )

        logger.info(
            "Created %s for %s (%d new concepts, %d new arcs)",
            new_version.version_id, accession,
            len(diff_result.new_concepts),
            len(diff_result.new_calc_arcs) + len(diff_result.new_dimension_arcs),
        )
        return new_version

    finally:
        cntlr.modelManager.close()
        cntlr.close()
