"""Generates provenance reports for processed SEC filings."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from config import PROJECT_ROOT
from schema.graph import SchemaGraph
from schema.schema_types import SchemaVersion

logger = logging.getLogger(__name__)

REPORTS_DIR = PROJECT_ROOT / "reports"


@dataclass
class FilingReport:
    accession: str
    form: str
    date: str
    schema_version_id: str
    schema_version_hash: str

    standard_concepts: list[dict] = field(default_factory=list)
    company_extensions: list[dict] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)

    calc_trees: list[dict] = field(default_factory=list)
    dimension_axes: list[dict] = field(default_factory=list)

    generated_at: str = ""


def build_report(
    version: SchemaVersion,
    accession: str,
    form: str,
    date: str,
) -> FilingReport:
    """
    Build a report from a SchemaVersion.
    """
    from datetime import datetime, timezone

    logger.info(
        "[%s] Building report: version=%s, form=%s, date=%s",
        accession, version.version_id, form, date,
    )

    report = FilingReport(
        accession=accession,
        form=form,
        date=date,
        schema_version_id=version.version_id,
        schema_version_hash=version.content_hash,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    # Concepts
    for c in version.concepts:
        item = {
            "name": c.name,
            "namespace_type": c.namespace_type,
            "label": c.label,
            "is_total": c.is_total,
            "is_component": c.is_component,
        }
        if c.namespace_type == "STANDARD":
            report.standard_concepts.append(item)
        else:
            report.company_extensions.append(item)

    # Unresolved
    for c in version.unresolved:
        report.unresolved.append({
            "name": c.name,
            "namespace_type": c.namespace_type,
        })

    # Calc trees (walk from totals)
    graph = SchemaGraph.from_version(version)
    for c in version.concepts:
        if c.is_total and c.namespace_type == "STANDARD":
            children = graph.calc_children(c.name)
            if children:
                report.calc_trees.append({
                    "total": c.name,
                    "components": [
                        {"name": child, "weight": weight}
                        for child, weight in children
                    ],
                })

    # Dimension axes
    for arc in version.dimension_arcs:
        # Group by axis
        existing = next((a for a in report.dimension_axes if a["axis"] == arc.axis_name), None)
        if existing:
            existing["members"].append(arc.member_name)
        else:
            report.dimension_axes.append({
                "axis": arc.axis_name,
                "members": [arc.member_name],
            })

    return report


def save_report(report: FilingReport) -> Path:
    """Serialize report to JSON."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{report.accession}.json"

    data = {
        "accession": report.accession,
        "form": report.form,
        "date": report.date,
        "schema_version": {
            "id": report.schema_version_id,
            "hash": report.schema_version_hash,
        },
        "concepts": {
            "standard": report.standard_concepts,
            "company": report.company_extensions,
        },
        "unresolved": report.unresolved,
        "calculation_trees": report.calc_trees,
        "dimension_axes": report.dimension_axes,
        "generated_at": report.generated_at,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)

    logger.info(
        "[%s] Saved report: %s (standard=%d, company=%d, unresolved=%d)",
        report.accession, path,
        len(report.standard_concepts), len(report.company_extensions),
        len(report.unresolved),
    )
    return path


def load_report(accession: str) -> dict | None:
    """Load a report by accession number."""
    path = REPORTS_DIR / f"{accession}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
