
"""
schema_types.py

 Immutable data structures for schema versions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class Concept:
    """
    A single concept in the schema — either standard or company-invented.
    Frozen + slots = lightweight, hashable, JSON-serializable.
    """
    name: str
    namespace_uri: str
    namespace_type: str  # "STANDARD" | "COMPANY" | "OTHER"
    label: str | None
    is_total: bool = False      # True if parent in calc arcs
    is_component: bool = False  # True if child in calc arcs


@dataclass(frozen=True, slots=True)
class CalcArc:
    """A summation-item arc: parent → child with weight."""
    parent_name: str
    child_name: str
    weight: float
    order: float


@dataclass(frozen=True, slots=True)
class DimensionArc:
    """A dimensional relationship: axis → member."""
    axis_name: str
    member_name: str
    member_namespace_type: str


@dataclass(frozen=True, slots=True)
class SchemaVersion:
    """
    Immutable snapshot of the schema at a point in time.
    
    version_id: "v0" for standard taxonomy baseline, "v1", "v2", etc.
    parent_version_id: None for v0, otherwise the version this extends.
    source_filing: Accession number that triggered this version (None for v0).
    taxonomy_year: e.g., "2025" — the US-GAAP taxonomy year declared.
    content_hash: SHA-256 of the debt-relevant subgraph. Used for no-op detection.
    """
    version_id: str
    parent_version_id: str | None
    source_filing: str | None
    taxonomy_year: str | None
    
    concepts: tuple[Concept, ...] = field(default_factory=tuple)
    calc_arcs: tuple[CalcArc, ...] = field(default_factory=tuple)
    dimension_arcs: tuple[DimensionArc, ...] = field(default_factory=tuple)
    unresolved: tuple[Concept, ...] = field(default_factory=tuple)
    
    content_hash: str = ""

    def compute_hash(self) -> str:
        """
        Hash only the debt-relevant subgraph for no-op detection.
        If APLD adds a revenue concept but doesn't touch debt, this hash stays the same.
        """
        data = {
            "concepts": sorted([
                {"name": c.name, "ns": c.namespace_type, "total": c.is_total, "comp": c.is_component}
                for c in self.concepts
            ], key=lambda x: x["name"]),
            "calc_arcs": sorted([
                {"from": a.parent_name, "to": a.child_name, "w": a.weight}
                for a in self.calc_arcs
            ], key=lambda x: (x["from"], x["to"])),
            "dimension_arcs": sorted([
                {"axis": a.axis_name, "member": a.member_name}
                for a in self.dimension_arcs
            ], key=lambda x: (x["axis"], x["member"])),
        }
        json_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()[:16]  # 16 chars is enough

    def with_hash(self) -> SchemaVersion:
        """Return a new SchemaVersion with content_hash computed."""
        return SchemaVersion(
            version_id=self.version_id,
            parent_version_id=self.parent_version_id,
            source_filing=self.source_filing,
            taxonomy_year=self.taxonomy_year,
            concepts=self.concepts,
            calc_arcs=self.calc_arcs,
            dimension_arcs=self.dimension_arcs,
            unresolved=self.unresolved,
            content_hash=self.compute_hash(),
        )