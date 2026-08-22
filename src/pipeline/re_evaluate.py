
"""
re_evaluate.py

 Self-healing re-evaluation.
After schema grows, re-classify prior filings' unresolved concepts
against the NEW schema — without mutating historical versions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from schema.diff_engine import DiffEngine, NEW_EXTENSION_UNRESOLVED
from schema.version_store import SchemaStore
from schema.schema_types import SchemaVersion

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("reports")


@dataclass
class ReEvaluationReport:
    """
    Report showing what we NOW understand about a historical filing,
    using the latest schema. The historical schema version is unchanged.
    """
    filing_accession: str
    historical_schema_version: str
    latest_schema_version: str
    previously_unresolved: list[str] = field(default_factory=list)
    now_resolved: list[dict] = field(default_factory=list)
    still_unresolved: list[str] = field(default_factory=list)


def re_evaluate_filing(
    accession: str,
    latest_schema: SchemaVersion,
    store: SchemaStore,
) -> ReEvaluationReport | None:
    """
    Re-classify a historical filing's concepts against the latest schema.

    Design:
    - Load the historical diff report (or re-extract concepts)
    - Re-run classification against latest schema
    - Compare: what was UNRESOLVED before vs now
    - Historical schema version remains immutable
    """
    # Find the schema version that was used for this filing
    historical = store.get_version_for_accession(accession)
    if historical is None:
        logger.warning("No historical version found for %s", accession)
        return None

    report = ReEvaluationReport(
        filing_accession=accession,
        historical_schema_version=historical.version_id,
        latest_schema_version=latest_schema.version_id,
    )

    # Load historical version's unresolved concepts
    report.previously_unresolved = [
        c.name for c in historical.unresolved
    ]

    if not report.previously_unresolved:
        logger.info("No unresolved concepts in %s to re-evaluate", accession)
        return report

    # Re-classify against latest schema
    engine = DiffEngine(latest_schema)

    for concept_name in report.previously_unresolved:
        # Simulate classification (we don't have the original Arelle concept,
        # so we do a name-based lookup against the latest schema)
        if concept_name in {c.name for c in latest_schema.concepts}:
            report.now_resolved.append({
                "name": concept_name,
                "reason": "Now exists in schema as extension",
            })
        else:
            report.still_unresolved.append(concept_name)

    logger.info(
        "Re-evaluated %s: %d previously unresolved, %d now resolved, %d still unresolved",
        accession,
        len(report.previously_unresolved),
        len(report.now_resolved),
        len(report.still_unresolved),
    )
    return report


def re_evaluate_all_historical(
    latest_version_id: str | None = None,
) -> list[ReEvaluationReport]:
    """
    Re-evaluate all prior filings against the latest schema.
    """
    store = SchemaStore(Path("schema_versions"))

    if latest_version_id is None:
        latest_version_id = store._latest_version_id()

    latest = store.get_version(latest_version_id) if latest_version_id else None
    if latest is None:
        logger.error("No latest schema version found")
        return []

    reports = []
    for version_id in store.list_versions():
        if version_id == latest_version_id:
            continue  # Don't re-evaluate the latest version against itself

        version = store.get_version(version_id)
        if version and version.source_filing:
            report = re_evaluate_filing(version.source_filing, latest, store)
            if report:
                reports.append(report)

    return reports


def save_report(report: ReEvaluationReport) -> Path:
    """Save re-evaluation report to reports/ directory."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"reval_{report.filing_accession}.json"

    data = {
        "filing_accession": report.filing_accession,
        "historical_schema_version": report.historical_schema_version,
        "latest_schema_version": report.latest_schema_version,
        "previously_unresolved": report.previously_unresolved,
        "now_resolved": report.now_resolved,
        "still_unresolved": report.still_unresolved,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)

    logger.info("Saved re-evaluation report: %s", path)
    return path
