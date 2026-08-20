
"""
dimension_extractor.py

 Extract XBRL Dimensions (definition linkbase) structures.
Finds axes, members, and hypercubes related to debt concepts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from xbrl_utils import (
    classify_namespace,
    DEBT_KEYWORDS,
    DIM_ALL,
    DIM_HYPERCUBE_DIMENSION,
    DIM_DIMENSION_DOMAIN,
    DIM_DOMAIN_MEMBER,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DimensionMember:
    name: str
    namespace_type: str
    label: str | None


@dataclass(frozen=True, slots=True)
class DimensionAxis:
    name: str
    namespace_type: str
    label: str | None
    members: list[DimensionMember] = field(default_factory=list)


class DimensionExtractor:
    """
    Extracts dimensional breakdowns from the definition linkbase.
    
    APLD uses dimensions to break debt into instruments (CIM, Macquarie, etc.)
    rather than calc arcs. This extractor finds those structures.
    """

    def __init__(self, model_xbrl):
        self.model = model_xbrl
        self.hypercube_dim = model_xbrl.relationshipSet(DIM_HYPERCUBE_DIMENSION)
        self.dim_domain = model_xbrl.relationshipSet(DIM_DIMENSION_DOMAIN)
        self.domain_member = model_xbrl.relationshipSet(DIM_DOMAIN_MEMBER)
        self.all_rel = model_xbrl.relationshipSet(DIM_ALL)

    def is_debt_related(self, concept) -> bool:
        """Check if concept name/label matches debt keywords."""
        name = str(concept.qname.localName).lower()
        text = name
        # Try to get label
        label_rel = self.model.relationshipSet(
            "http://www.xbrl.org/2003/arcrole/concept-label"
        )
        if label_rel:
            try:
                label = label_rel.label(concept, lang="en-US")
                if label:
                    text += " " + label.lower()
            except Exception:
                pass
        return any(kw in text for kw in DEBT_KEYWORDS)

    def find_debt_axes(self) -> list[DimensionAxis]:
        """
        Find dimension axes that are debt-related and extract their members.
        """
        axes: list[DimensionAxis] = []
        seen_axes: set[str] = set()

        # Strategy: Find all dimension concepts, filter by debt keyword
        for qname_obj, concept in self.model.qnameConcepts.items():
            name = str(qname_obj.localName)
            
            # Dimensions often end in "Axis" or "Table"
            if not (name.endswith("Axis") or name.endswith("Table")):
                continue
            
            if not self.is_debt_related(concept):
                continue
            
            axis_qname = str(qname_obj)
            if axis_qname in seen_axes:
                continue
            seen_axes.add(axis_qname)

            # Walk domain-member relationships to find members
            members = self._get_axis_members(concept)
            
            axes.append(DimensionAxis(
                name=name,
                namespace_type=classify_namespace(str(qname_obj.namespaceURI)),
                label=None,  # Could fetch label if needed
                members=members,
            ))
        
        return axes

    def _get_axis_members(self, axis_concept) -> list[DimensionMember]:
        """
        Walk dimension → domain → member chains to collect members.
        
        XBRL dimensions link: Axis → (dimension-domain arc) → Domain → (domain-member arc) → Members
        """
        members: list[DimensionMember] = []
        seen: set[str] = set()
        
        # Step 1: Walk dimension-domain arcs from the axis to find domains
        if not self.dim_domain:
            return members
        
        for dd_rel in self.dim_domain.fromModelObject(axis_concept):
            domain = dd_rel.toModelObject
            if domain is None:
                continue
            
            # Step 2: Walk domain-member arcs from each domain to find members
            if not self.domain_member:
                continue
            
            for dm_rel in self.domain_member.fromModelObject(domain):
                member_concept = dm_rel.toModelObject
                if member_concept is None:
                    continue
                
                member_qname = str(member_concept.qname)
                if member_qname in seen:
                    continue
                seen.add(member_qname)
                
                members.append(DimensionMember(
                    name=str(member_concept.qname.localName),
                    namespace_type=classify_namespace(str(member_concept.qname.namespaceURI)),
                    label=None,
                ))
        
        return members

    def find_debt_facts_by_dimension(self) -> dict:
        """
        Inspect instance facts to find which dimension-member combos
        have debt-related values.
        
        Uses model.contexts dict (id → ModelContext) and ctx.segDimValues
        where keys are ModelConcept objects and values are ModelDimensionValue objects.
        """
        results: dict[str, list[str]] = {}
        
        # Build a map of context_id → dimension strings for efficient lookup
        ctx_dims: dict[str, list[str]] = {}
        for ctx_id, ctx in self.model.contexts.items():
            seg_dims = getattr(ctx, "segDimValues", None) or {}
            if not seg_dims:
                continue
            dims: list[str] = []
            for dim_concept, dim_val in seg_dims.items():
                # dim_concept is a ModelConcept, dim_val is a ModelDimensionValue
                dim_name = str(dim_concept.qname.localName)
                if hasattr(dim_val, "memberQname") and dim_val.memberQname is not None:
                    member_name = str(dim_val.memberQname.localName)
                else:
                    member_name = str(dim_val)
                dims.append(f"{dim_name}={member_name}")
            ctx_dims[ctx_id] = dims
        
        # Now walk facts and attach dimension info from their contexts
        for fact in self.model.facts:
            concept = fact.concept
            if concept is None:
                continue
            
            if not self.is_debt_related(concept):
                continue
            
            # fact.contextId gives the context ID string
            ctx_id = getattr(fact, "contextID", None) or getattr(fact, "contextId", None)
            if ctx_id is None:
                continue
            
            dims = ctx_dims.get(ctx_id)
            if dims:
                fact_key = str(concept.qname.localName)
                if fact_key not in results:
                    results[fact_key] = []
                results[fact_key].extend(dims)
        
        return results


def print_dimensions(axes: list[DimensionAxis]) -> None:
    print(f"\n{'='*60}")
    print("DEBT-RELATED DIMENSION AXES")
    print(f"{'='*60}")
    
    for axis in axes:
        print(f"\n[{axis.namespace_type}] {axis.name}")
        if axis.members:
            for m in axis.members:
                marker = "*" if m.namespace_type == "COMPANY" else " "
                print(f"  {marker} {m.name}")
        else:
            print("  (no members extracted)")
    
    print(f"\nTotal axes found: {len(axes)}")