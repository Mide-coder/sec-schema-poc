
"""
standard_taxonomy_bootstrap.py

 Build the standard US-GAAP debt concept seed list by walking
calculation arcs from known standard debt roots within the loaded model.
This becomes Schema v0 — the baseline before any company extensions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from xbrl_utils import (
    classify_namespace,
    DEBT_KEYWORDS,
    US_GAAP_DEBT_ROOTS,
    STANDARD_URI_FRAGMENTS,
)

logger = logging.getLogger(__name__)

SUMMATION_ITEM_ARCROLE = "http://www.xbrl.org/2003/arcrole/summation-item"


@dataclass(frozen=True, slots=True)
class StandardDebtConcept:
    name: str
    namespace_uri: str
    label: str | None
    is_total: bool  # True if it's a parent in calc arcs
    is_component: bool  # True if it's a child in calc arcs


class StandardTaxonomyBootstrap:
    """
    Extracts the debt-relevant subgraph from the standard US-GAAP taxonomy.
    
    Since Arelle loads the standard taxonomy as part of the DTS when loading
    an APLD filing, we can walk the calc tree directly from the model without
    a separate network fetch.
    """

    def __init__(self, model_xbrl):
        self.model = model_xbrl
        self.calc_rel_set = model_xbrl.relationshipSet(SUMMATION_ITEM_ARCROLE)

    def is_standard_concept(self, concept) -> bool:
        """Check if a concept belongs to a standard namespace."""
        ns = str(concept.qname.namespaceURI).lower()
        return any(s in ns for s in STANDARD_URI_FRAGMENTS)

    def find_standard_debt_roots(self) -> list:
        """
        Find standard concepts that match known debt root names.
        These are the starting points for calc tree walks.
        """
        roots = []
        seen: set[str] = set()
        
        for qname_obj, concept in self.model.qnameConcepts.items():
            if not self.is_standard_concept(concept):
                continue
            
            name = str(qname_obj.localName)
            if name in US_GAAP_DEBT_ROOTS:
                qname_str = str(qname_obj)
                if qname_str not in seen:
                    seen.add(qname_str)
                    roots.append(concept)
        
        roots.sort(key=lambda c: str(c.qname.localName))
        logger.info("Found %d standard debt root concepts", len(roots))
        return roots

    def walk_calc_descendants(self, root_concept, visited: set[str] | None = None) -> list[StandardDebtConcept]:
        """
        Walk calc arcs from a root, collecting all standard concepts reachable.
        """
        if visited is None:
            visited = set()
        
        results: list[StandardDebtConcept] = []
        qname_str = str(root_concept.qname)
        
        if qname_str in visited:
            return results
        visited.add(qname_str)
        
        # Add the root itself
        results.append(StandardDebtConcept(
            name=str(root_concept.qname.localName),
            namespace_uri=str(root_concept.qname.namespaceURI),
            label=None,  # Labels fetched separately if needed
            is_total=True,
            is_component=False,
        ))
        
        if not self.calc_rel_set:
            return results
        
        # Walk children
        for rel in self.calc_rel_set.fromModelObject(root_concept):
            child = rel.toModelObject
            if child is None:
                continue
            
            if not self.is_standard_concept(child):
                continue  # Skip company extensions in standard bootstrap
            
            child_qname = str(child.qname)
            if child_qname not in visited:
                results.append(StandardDebtConcept(
                    name=str(child.qname.localName),
                    namespace_uri=str(child.qname.namespaceURI),
                    label=None,
                    is_total=False,
                    is_component=True,
                ))
                # Recurse
                results.extend(self.walk_calc_descendants(child, visited))
        
        return results

    def build_seed_list(self) -> list[StandardDebtConcept]:
        """
        Build the complete standard debt concept seed list.
        Walks from all known roots and deduplicates.
        """
        all_concepts: dict[str, StandardDebtConcept] = {}
        
        for root in self.find_standard_debt_roots():
            descendants = self.walk_calc_descendants(root)
            for concept in descendants:
                key = f"{concept.namespace_uri}#{concept.name}"
                if key not in all_concepts:
                    all_concepts[key] = concept
                else:
                    # Merge flags: a concept can be both total and component
                    existing = all_concepts[key]
                    all_concepts[key] = StandardDebtConcept(
                        name=existing.name,
                        namespace_uri=existing.namespace_uri,
                        label=existing.label,
                        is_total=existing.is_total or concept.is_total,
                        is_component=existing.is_component or concept.is_component,
                    )
        
        return sorted(all_concepts.values(), key=lambda c: c.name)


def print_seed_list(seed: list[StandardDebtConcept]) -> None:
    print(f"\n{'='*60}")
    print(f"STANDARD US-GAAP DEBT CONCEPT SEED LIST")
    print(f"{'='*60}")
    print(f"{'Name':<40} {'Total':<6} {'Comp':<6}")
    print("-" * 60)
    
    for c in seed:
        total = "YES" if c.is_total else ""
        comp = "YES" if c.is_component else ""
        print(f"{c.name:<40} {total:<6} {comp:<6}")
    
    print(f"\nTotal standard debt concepts: {len(seed)}")