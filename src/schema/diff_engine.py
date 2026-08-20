
"""
diff_engine.py

Day 8: The self-healing core. Classifies every debt concept in a new filing
against the current schema version.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from arelle import XbrlConst

from schema.schema_types import SchemaVersion, Concept, CalcArc, DimensionArc
from schema.graph import SchemaGraph
from xbrl_utils import classify_namespace, DEBT_KEYWORDS

logger = logging.getLogger(__name__)

#  Classification categories 

MATCHES_STANDARD = "MATCHES_STANDARD"
MATCHES_EXISTING_EXTENSION = "MATCHES_EXISTING_EXTENSION"
NEW_EXTENSION_RESOLVED = "NEW_EXTENSION_RESOLVED"
NEW_EXTENSION_UNRESOLVED = "NEW_EXTENSION_UNRESOLVED"
RELATED_NOT_COMBINABLE = "RELATED_NOT_COMBINABLE"


#  Result types 

@dataclass(frozen=True, slots=True)
class ConceptClassification:
    concept_name: str
    namespace_type: str
    classification: str
    evidence: str
    matched_concept: str | None = None


@dataclass
class DiffResult:
    filing_accession: str
    prior_version_id: str
    new_version_id: str | None = None
    classifications: list[ConceptClassification] = field(default_factory=list)
    new_concepts: list[Concept] = field(default_factory=list)
    new_calc_arcs: list[CalcArc] = field(default_factory=list)
    new_dimension_arcs: list[DimensionArc] = field(default_factory=list)


#  DiffEngine 

class DiffEngine:
    """
    Compares a filing's debt concepts against the current schema version
    and classifies each as one of five categories.
    """

    def __init__(self, current_version: SchemaVersion):
        self.current_version = current_version
        self._standard_names = {
            c.name for c in current_version.concepts
            if c.namespace_type == "STANDARD"
        }
        self._company_names = {
            c.name for c in current_version.concepts
            if c.namespace_type == "COMPANY"
        }
        self._all_names = {c.name for c in current_version.concepts}
        self.graph = SchemaGraph.from_version(current_version)

        # Keywords that indicate a concept should NOT be summed into debt totals
        self._not_combinable = frozenset([
            "issuancecost", "discount", "deferredfinancing", "premium",
            "debtissuance", "unamortized", "deferredcost", "issuance",
        ])

    #  Public API 

    def diff_filing(self, model_xbrl, accession: str) -> DiffResult:
        """
        Main entry point. Extracts all debt concepts from a filing,
        classifies each, and identifies new relationships.
        """
        result = DiffResult(
            filing_accession=accession,
            prior_version_id=self.current_version.version_id,
        )

        filing_concepts = self._extract_debt_concepts(model_xbrl)

        for name, ns_type, label, concept in filing_concepts:
            classification = self._classify(name, ns_type, label, model_xbrl, concept)
            result.classifications.append(classification)

            if classification.classification == NEW_EXTENSION_RESOLVED:
                result.new_concepts.append(Concept(
                    name=name,
                    namespace_uri=str(concept.qname.namespaceURI),
                    namespace_type=ns_type,
                    label=label,
                ))

        result.new_calc_arcs = self._find_new_calc_arcs(model_xbrl)
        result.new_dimension_arcs = self._find_new_dimension_arcs(model_xbrl)

        logger.info(
            "Diff %s: %d concepts, %d resolved, %d unresolved, %d not-combinable, %d new arcs",
            accession,
            len(result.classifications),
            sum(1 for c in result.classifications if c.classification == NEW_EXTENSION_RESOLVED),
            sum(1 for c in result.classifications if c.classification == NEW_EXTENSION_UNRESOLVED),
            sum(1 for c in result.classifications if c.classification == RELATED_NOT_COMBINABLE),
            len(result.new_calc_arcs) + len(result.new_dimension_arcs),
        )
        return result

    #  Classification logic 

    def _classify(
        self,
        name: str,
        ns_type: str,
        label: str | None,
        model_xbrl,
        concept,
    ) -> ConceptClassification:
        # 1. Standard concept
        if ns_type == "STANDARD":
            if name in self._standard_names:
                return ConceptClassification(
                    name, ns_type, MATCHES_STANDARD,
                    "Exact name match to standard concept in schema", name
                )
            return ConceptClassification(
                name, ns_type, MATCHES_STANDARD,
                "Standard namespace concept (new standard taxonomy element)", None
            )

        # 2. Existing company extension
        if name in self._company_names and ns_type == "COMPANY":
            return ConceptClassification(
                name, ns_type, MATCHES_EXISTING_EXTENSION,
                "Exact name match to existing company extension in schema", name
            )

        # 3. Not combinable
        if self._is_not_combinable(name, label, model_xbrl, concept):
            return ConceptClassification(
                name, ns_type, RELATED_NOT_COMBINABLE,
                "Negative calc weight or matches not-combinable keyword list", None
            )

        # 4. Resolved via relationship evidence
        evidence = self._find_relationship_evidence(name, model_xbrl, concept)
        if evidence:
            return ConceptClassification(
                name, ns_type, NEW_EXTENSION_RESOLVED,
                evidence, None
            )

        # 5. Unresolved
        return ConceptClassification(
            name, ns_type, NEW_EXTENSION_UNRESOLVED,
            "No exact match, no calc/dimension/presentation link to known concept, not explicitly excluded",
            None
        )

    #  Evidence detectors 

    def _is_not_combinable(self, name, label, model_xbrl, concept):
        combined = f"{name} {label or ''}".lower().replace(" ", "")
        if any(kw in combined for kw in self._not_combinable):
            return True
        if concept is None or model_xbrl is None:
            return False
        calc_rel_set = model_xbrl.relationshipSet(
            "http://www.xbrl.org/2003/arcrole/summation-item"
        )
        if calc_rel_set:
            for rel in calc_rel_set.toModelObject(concept):
                parent = rel.fromModelObject
                if parent and str(parent.qname.localName) in self._all_names:
                    if getattr(rel, "weight", 1.0) < 0:
                        return True
        return False

    def _find_relationship_evidence(self, name, model_xbrl, concept):
        if concept is None or model_xbrl is None:
            return None

        # Calc arc
        calc_rel_set = model_xbrl.relationshipSet(
            "http://www.xbrl.org/2003/arcrole/summation-item"
        )
        if calc_rel_set:
            for rel in calc_rel_set.toModelObject(concept):
                parent = rel.fromModelObject
                if parent:
                    parent_name = str(parent.qname.localName)
                    if parent_name in self._all_names:
                        w = getattr(rel, "weight", 1.0)
                        return f"Calc arc: component of {parent_name} (weight={w:+.1f})"

        # Dimension member
        dim_member_set = model_xbrl.relationshipSet(
            "http://xbrl.org/int/dim/arcrole/dimension-domain"
        )
        if dim_member_set:
            for rel in dim_member_set.toModelObject(concept):
                parent = rel.fromModelObject
                if parent:
                    parent_name = str(parent.qname.localName)
                    if parent_name in self._all_names:
                        return f"Dimension member of {parent_name}"

        # Presentation child
        pre_rel_set = model_xbrl.relationshipSet(
            "http://www.xbrl.org/2003/arcrole/parent-child"
        )
        if pre_rel_set:
            for rel in pre_rel_set.toModelObject(concept):
                parent = rel.fromModelObject
                if parent:
                    parent_name = str(parent.qname.localName)
                    if parent_name in self._all_names:
                        return f"Presentation child of {parent_name}"

        return None

    #  Relationship extraction 

    def _find_new_calc_arcs(self, model_xbrl) -> list[CalcArc]:
        new_arcs = []
        existing = {
            (a.parent_name, a.child_name)
            for a in self.current_version.calc_arcs
        }
        calc_rel_set = model_xbrl.relationshipSet(
            "http://www.xbrl.org/2003/arcrole/summation-item"
        )
        if not calc_rel_set:
            return new_arcs

        for rel in calc_rel_set.modelRelationships:
            parent = rel.fromModelObject
            child = rel.toModelObject
            if parent is None or child is None:
                continue
            parent_name = str(parent.qname.localName)
            child_name = str(child.qname.localName)
            if (parent_name, child_name) not in existing:
                if parent_name in self._all_names or child_name in self._all_names:
                    new_arcs.append(CalcArc(
                        parent_name=parent_name,
                        child_name=child_name,
                        weight=getattr(rel, "weight", 1.0),
                        order=getattr(rel, "order", 0.0),
                    ))
        return new_arcs

    def _find_new_dimension_arcs(self, model_xbrl) -> list[DimensionArc]:
        new_arcs = []
        existing = {
            (a.axis_name, a.member_name)
            for a in self.current_version.dimension_arcs
        }
        dim_member_set = model_xbrl.relationshipSet(
            "http://xbrl.org/int/dim/arcrole/dimension-domain"
        )
        if not dim_member_set:
            return new_arcs

        for rel in dim_member_set.modelRelationships:
            parent = rel.fromModelObject
            child = rel.toModelObject
            if parent is None or child is None:
                continue
            axis_name = str(parent.qname.localName)
            member_name = str(child.qname.localName)
            if (axis_name, member_name) not in existing:
                new_arcs.append(DimensionArc(
                    axis_name=axis_name,
                    member_name=member_name,
                    member_namespace_type=classify_namespace(str(child.qname.namespaceURI)),
                ))
        return new_arcs

    #  Concept extraction 

    def _extract_debt_concepts(self, model_xbrl):
        concepts = []
        label_rel_set = model_xbrl.relationshipSet(
            "http://www.xbrl.org/2003/arcrole/concept-label"
        )
        for qname_obj, concept in model_xbrl.qnameConcepts.items():
            name = str(qname_obj.localName)
            ns = str(qname_obj.namespaceURI)
            ns_type = classify_namespace(ns)

            label = None
            if label_rel_set:
                try:
                    label = label_rel_set.label(
                        concept,
                        role=XbrlConst.standardLabel,
                        lang="en-US",
                    )
                except Exception:
                    pass

            text = f"{name} {label or ''}".lower()
            if not any(kw in text for kw in DEBT_KEYWORDS):
                continue

            concepts.append((name, ns_type, label, concept))
        return concepts