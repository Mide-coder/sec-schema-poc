"""Classifies debt concepts in new filings against the active schema version."""

import logging
from dataclasses import dataclass, field

from arelle import XbrlConst

from schema.graph import SchemaGraph
from schema.schema_types import CalcArc, Concept, DimensionArc, SchemaVersion
from xbrl_utils import DEBT_KEYWORDS, classify_namespace

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

    def __init__(self, current_version: SchemaVersion, previously_unresolved: set[str] | None = None):
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

        # Track all names that were ever unresolved across schema history.
        # Once a concept is resolved (added to concepts), it must never
        # revert to unresolved — carry the resolved status forward.
        # If previously_unresolved is provided, use the accumulated set;
        # otherwise fall back to the current version's unresolved list.
        if previously_unresolved is not None:
            self._previously_unresolved = previously_unresolved
        else:
            self._previously_unresolved = {
                c.name for c in current_version.unresolved
            }

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
        logger.info(
            "[%s] Extracted %d debt concepts from filing",
            accession, len(filing_concepts),
        )

        for name, ns_type, label, concept in filing_concepts:
            classification = self._classify(name, ns_type, label, model_xbrl, concept)
            result.classifications.append(classification)

            logger.info(
                "[%s] Classified %s (%s) as %s — %s",
                accession, name, ns_type, classification.classification,
                classification.evidence,
            )

            if classification.classification == NEW_EXTENSION_RESOLVED:
                result.new_concepts.append(Concept(
                    name=name,
                    namespace_uri=str(concept.qname.namespaceURI),
                    namespace_type=ns_type,
                    label=label,
                ))

        result.new_calc_arcs = self._find_new_calc_arcs(model_xbrl)
        result.new_dimension_arcs = self._find_new_dimension_arcs(model_xbrl)

        for arc in result.new_calc_arcs:
            logger.info(
                "[%s] New calc arc: %s -> %s (weight=%+.1f)",
                accession, arc.parent_name, arc.child_name, arc.weight,
            )
        for arc in result.new_dimension_arcs:
            logger.info(
                "[%s] New dimension arc: %s -> %s (ns=%s)",
                accession, arc.axis_name, arc.member_name, arc.member_namespace_type,
            )

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

        # 2b. Previously unresolved — allow resolution if evidence exists.
        # A concept that was unresolved in a prior version may become resolved
        # when a later filing provides relationship evidence (domain-member arc,
        # calc arc, or presentation link).  However, it must NOT revert to
        # NEW_EXTENSION_UNRESOLVED if the current filing's linkbase simply
        # lacks the evidence that resolved it before.
        if name in self._previously_unresolved:
            evidence = self._find_relationship_evidence(name, model_xbrl, concept)
            if evidence:
                return ConceptClassification(
                    name, ns_type, NEW_EXTENSION_RESOLVED,
                    evidence, None
                )
            return ConceptClassification(
                name, ns_type, MATCHES_EXISTING_EXTENSION,
                "Previously unresolved — carried forward as known company extension", name
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
                if parent is not None and str(parent.qname.localName) in self._all_names:
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
                if parent is not None:
                    parent_name = str(parent.qname.localName)
                    if parent_name in self._all_names:
                        w = getattr(rel, "weight", 1.0)
                        return f"Calc arc: component of {parent_name} (weight={w:+.1f})"

        # Dimension domain (axis -> domain)
        dim_member_set = model_xbrl.relationshipSet(
            "http://xbrl.org/int/dim/arcrole/dimension-domain"
        )
        if dim_member_set:
            for rel in dim_member_set.toModelObject(concept):
                parent = rel.fromModelObject
                if parent is not None:
                    parent_name = str(parent.qname.localName)
                    parent_ns = str(parent.qname.namespaceURI)
                    # Accept if parent is in schema OR is a standard taxonomy axis
                    if parent_name in self._all_names or classify_namespace(parent_ns) == "STANDARD":
                        return f"Dimension member of {parent_name}"

        # Domain member (domain -> member) — XBRL 3-step dimension pattern
        domain_member_set = model_xbrl.relationshipSet(
            "http://xbrl.org/int/dim/arcrole/domain-member"
        )
        if domain_member_set:
            for rel in domain_member_set.toModelObject(concept):
                parent = rel.fromModelObject
                if parent is not None:
                    parent_name = str(parent.qname.localName)
                    parent_ns = str(parent.qname.namespaceURI)
                    if classify_namespace(parent_ns) == "STANDARD":
                        return f"Domain member of {parent_name} (standard domain)"

        # Presentation child
        pre_rel_set = model_xbrl.relationshipSet(
            "http://www.xbrl.org/2003/arcrole/parent-child"
        )
        if pre_rel_set:
            for rel in pre_rel_set.toModelObject(concept):
                parent = rel.fromModelObject
                if parent is not None:
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

        # dimension-domain arcs (axis -> domain)
        dim_member_set = model_xbrl.relationshipSet(
            "http://xbrl.org/int/dim/arcrole/dimension-domain"
        )
        if dim_member_set:
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

        # domain-member arcs (domain -> member) — XBRL 3-step dimension pattern
        domain_member_set = model_xbrl.relationshipSet(
            "http://xbrl.org/int/dim/arcrole/domain-member"
        )
        if domain_member_set:
            for rel in domain_member_set.modelRelationships:
                parent = rel.fromModelObject
                child = rel.toModelObject
                if parent is None or child is None:
                    continue
                domain_name = str(parent.qname.localName)
                member_name = str(child.qname.localName)
                if (domain_name, member_name) not in existing:
                    new_arcs.append(DimensionArc(
                        axis_name=domain_name,
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

            # Seeding filter: non-standard concepts must have at least one
            # relationship (calc, domain-member, or presentation) to a concept
            # already in the schema — the confirmed debt-relevant family.
            # This prevents equity/compensation concepts that merely contain a
            # debt keyword (e.g. "Convertible" in PreferredStockConvertibleShares)
            # from entering the debt schema via a domain-member arc to a
            # non-debt standard taxonomy parent.
            if ns_type != "STANDARD":
                if not self._has_debt_family_relationship(concept, model_xbrl):
                    logger.debug(
                        "Seeding filter excluded %s: keyword match but "
                        "no relationship to existing debt-relevant concepts",
                        name,
                    )
                    continue

            concepts.append((name, ns_type, label, concept))
        return concepts

    def _has_debt_family_relationship(self, concept, model_xbrl) -> bool:
        """Check if a concept has at least one relationship to a concept
        in the debt-relevant family.

        The debt-relevant family includes:
        - Concepts already tracked in the schema (self._all_names)
        - Standard taxonomy concepts whose names match debt keywords
          (e.g. "Debt", "Note", "Warrant", "Loan", "ConvertibleDebt")

        This prevents equity/compensation concepts that merely contain a
        debt keyword (e.g. "Convertible") from entering the debt schema
        via a domain-member arc to a non-debt standard taxonomy parent
        like ShareBasedCompensationArrangementByShareBasedPaymentAwardLineItems.
        """
        if concept is None or model_xbrl is None:
            return False

        def _is_debt_family_name(name: str) -> bool:
            """Check if a concept name matches debt-related keywords."""
            name_lower = name.lower()
            return any(kw in name_lower for kw in DEBT_KEYWORDS)

        def _is_in_schema_or_debt_family(parent_name: str, parent_ns: str) -> bool:
            """Check if parent is in schema or has a debt-related name.

            Accepts:
            - Any concept already in the schema (self._all_names)
            - Any concept (standard or company) whose name matches debt
              keywords — e.g. NotePayableLineItems, WarrantAbstract,
              NetCashProvidedByUsedInFinancingActivitiesAbstract.

            This ensures new company extensions that are genuine debt concepts
            (connected to debt-related parents) pass the filter, while
            equity/compensation concepts (whose parents have names like
            ShareBasedCompensationArrangementByShareBasedPaymentAwardLineItems)
            are excluded.
            """
            if parent_name in self._all_names:
                return True
            result = _is_debt_family_name(parent_name)
            if not result:
                logger.debug(
                    "  _is_in_schema_or_debt_family REJECT: %s (ns=%s)"
                    " not in schema, no debt keyword match",
                    parent_name, parent_ns,
                )
            return result

        # Calc arcs (summation-item) — only check parents, not children.
        # When iterating toModelObject(concept), the concept is the child;
        # we only need to confirm the parent is in the debt family.
        calc_rel_set = model_xbrl.relationshipSet(
            "http://www.xbrl.org/2003/arcrole/summation-item"
        )
        if calc_rel_set:
            for rel in calc_rel_set.toModelObject(concept):
                parent = rel.fromModelObject
                if parent is not None:
                    pname = str(parent.qname.localName)
                    pns = str(parent.qname.namespaceURI)
                    if _is_in_schema_or_debt_family(pname, pns):
                        return True

        # Domain-member arcs (domain -> member)
        domain_member_set = model_xbrl.relationshipSet(
            "http://xbrl.org/int/dim/arcrole/domain-member"
        )
        if domain_member_set:
            for rel in domain_member_set.toModelObject(concept):
                parent = rel.fromModelObject
                if parent is not None:
                    pname = str(parent.qname.localName)
                    pns = str(parent.qname.namespaceURI)
                    if _is_in_schema_or_debt_family(pname, pns):
                        return True

        # Presentation arcs (parent-child) — only check parents
        pre_rel_set = model_xbrl.relationshipSet(
            "http://www.xbrl.org/2003/arcrole/parent-child"
        )
        if pre_rel_set:
            for rel in pre_rel_set.toModelObject(concept):
                parent = rel.fromModelObject
                if parent is not None:
                    pname = str(parent.qname.localName)
                    pns = str(parent.qname.namespaceURI)
                    if _is_in_schema_or_debt_family(pname, pns):
                        return True

        return False