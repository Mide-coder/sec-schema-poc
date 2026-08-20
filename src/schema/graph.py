#!/usr/bin/env python3
"""
graph.py

Day 7: networkx-based directed graph for schema concepts and relationships.
Builds SchemaVersion v0 from standard taxonomy, supports diff operations.
"""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx

from schema.schema_types import Concept, CalcArc, DimensionArc, SchemaVersion

logger = logging.getLogger(__name__)


class SchemaGraph:
    """
    Mutable builder for a schema version. Once built, freeze to SchemaVersion.

    Design:
    - DiGraph = directed (calc arcs have direction: total -> component)
    - Nodes = Concept objects (hashable, so networkx can use them as keys)
    - Edges have attributes: 'kind' ('calc'|'dimension'|'presentation'), 'weight', 'order'
    - Node attributes: 'namespace_type', 'label', 'is_total', 'is_component'
    """

    def __init__(self):
        self.g = nx.DiGraph()
        self._concept_map: dict[str, Concept] = {}  # name -> Concept for fast lookup

    # -- Building -----------------------------------------------------------

    def add_concept(self, concept: Concept) -> None:
        """Add or update a concept node."""
        self._concept_map[concept.name] = concept
        self.g.add_node(
            concept.name,
            namespace_type=concept.namespace_type,
            label=concept.label,
            is_total=concept.is_total,
            is_component=concept.is_component,
        )

    def add_calc_arc(self, arc: CalcArc) -> None:
        """Add a summation-item arc: parent -> child."""
        self.g.add_edge(
            arc.parent_name,
            arc.child_name,
            kind="calc",
            weight=arc.weight,
            order=arc.order,
        )

    def add_dimension_arc(self, arc: DimensionArc) -> None:
        """Add a dimension arc: axis -> member."""
        self.g.add_edge(
            arc.axis_name,
            arc.member_name,
            kind="dimension",
            member_namespace_type=arc.member_namespace_type,
        )

    # -- Queries ------------------------------------------------------------

    def get_concept(self, name: str) -> Concept | None:
        return self._concept_map.get(name)

    def has_concept(self, name: str) -> bool:
        return name in self._concept_map

    def calc_children(self, parent_name: str) -> list[tuple[str, float]]:
        """
        Return (child_name, weight) for all calc arcs from parent.
        Sorted by order attribute.
        """
        if parent_name not in self.g:
            return []

        edges = []
        for _, child, data in self.g.out_edges(parent_name, data=True):
            if data.get("kind") == "calc":
                edges.append((child, data.get("weight", 1.0), data.get("order", 0.0)))

        edges.sort(key=lambda x: x[2])  # Sort by order
        return [(c, w) for c, w, _ in edges]

    def calc_parents(self, child_name: str) -> list[tuple[str, float]]:
        """Return (parent_name, weight) for all calc arcs to child."""
        if child_name not in self.g:
            return []

        edges = []
        for parent, _, data in self.g.in_edges(child_name, data=True):
            if data.get("kind") == "calc":
                edges.append((parent, data.get("weight", 1.0)))
        return edges

    def dimension_members(self, axis_name: str) -> list[str]:
        """Return all member members of a dimension axis."""
        if axis_name not in self.g:
            return []

        members = []
        for _, child, data in self.g.out_edges(axis_name, data=True):
            if data.get("kind") == "dimension":
                members.append(child)
        return members

    def descendants(self, root: str) -> set[str]:
        """
        Return all nodes reachable from root via BFS.
        Includes calc and dimension edges.
        """
        if root not in self.g:
            return set()
        return nx.descendants(self.g, root)

    def is_reachable(self, source: str, target: str) -> bool:
        """Check if there's any path from source to target."""
        try:
            return nx.has_path(self.g, source, target)
        except nx.NodeNotFound:
            return False

    # -- Freezing -----------------------------------------------------------

    def to_version(
        self,
        version_id: str,
        parent_version_id: str | None = None,
        source_filing: str | None = None,
        taxonomy_year: str | None = None,
    ) -> SchemaVersion:
        """
        Freeze the current graph into an immutable SchemaVersion.
        Computes the hash to detect no-op changes.
        """
        concepts = tuple(sorted(self._concept_map.values(), key=lambda c: c.name))

        calc_arcs = []
        for u, v, data in self.g.edges(data=True):
            if data.get("kind") == "calc":
                calc_arcs.append(CalcArc(
                    parent_name=u,
                    child_name=v,
                    weight=data["weight"],
                    order=data.get("order", 0.0),
                ))
        calc_arcs = tuple(sorted(calc_arcs, key=lambda a: (a.parent_name, a.child_name)))

        dimension_arcs = []
        for u, v, data in self.g.edges(data=True):
            if data.get("kind") == "dimension":
                dimension_arcs.append(DimensionArc(
                    axis_name=u,
                    member_name=v,
                    member_namespace_type=data.get("member_namespace_type", "OTHER"),
                ))
        dimension_arcs = tuple(sorted(dimension_arcs, key=lambda a: (a.axis_name, a.member_name)))

        version = SchemaVersion(
            version_id=version_id,
            parent_version_id=parent_version_id,
            source_filing=source_filing,
            taxonomy_year=taxonomy_year,
            concepts=concepts,
            calc_arcs=calc_arcs,
            dimension_arcs=dimension_arcs,
            unresolved=tuple(),  # Populated by diff engine later
        )
        return version.with_hash()

    # -- Serialization ------------------------------------------------------

    @classmethod
    def from_version(cls, version: SchemaVersion) -> "SchemaGraph":
        """Reconstruct a mutable graph from a frozen SchemaVersion."""
        g = cls()
        for c in version.concepts:
            g.add_concept(c)
        for a in version.calc_arcs:
            g.add_calc_arc(a)
        for a in version.dimension_arcs:
            g.add_dimension_arc(a)
        return g
