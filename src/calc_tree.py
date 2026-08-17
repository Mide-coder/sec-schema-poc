
"""
calc_tree.py

Day 5: Extract calculation (summation-item) trees from Arelle models.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from arelle import XbrlConst
from xbrl_utils import classify_namespace, DEBT_KEYWORDS

logger = logging.getLogger(__name__)

SUMMATION_ITEM_ARCROLE = "http://www.xbrl.org/2003/arcrole/summation-item"
CONCEPT_LABEL_ARCROLE = "http://www.xbrl.org/2003/arcrole/concept-label"

# Filter out cash-flow concepts (they match "financing" but aren't debt balances)
CASH_FLOW_EXCLUDES = frozenset([
    "cash", "provided", "used", "activities",
])


def is_balance_sheet_debt(name: str) -> bool:
    name_lower = name.lower()
    if not any(kw in name_lower for kw in DEBT_KEYWORDS):
        return False
    # Exclude cash flow statement roll-ups
    if any(ex in name_lower for ex in CASH_FLOW_EXCLUDES):
        return False
    return True


@dataclass(frozen=True, slots=True)
class CalcNode:
    concept_name: str
    namespace_uri: str
    namespace_type: str
    label: str | None
    weight_from_parent: float
    order_from_parent: float
    children: list[CalcNode] = field(default_factory=list, compare=False)

    @property
    def is_root(self) -> bool:
        return self.weight_from_parent == 0.0


class CalcTreeExtractor:
    def __init__(self, model_xbrl):
        self.model = model_xbrl
        self.calc_rel_set = model_xbrl.relationshipSet(SUMMATION_ITEM_ARCROLE)
        self.label_rel_set = model_xbrl.relationshipSet(CONCEPT_LABEL_ARCROLE)

    def get_label(self, concept) -> str | None:
        if not self.label_rel_set:
            return None
        try:
            return self.label_rel_set.label(
                concept,
                role=XbrlConst.standardLabel,
                lang="en-US",
            )
        except Exception:
            return None

    def build_tree(
        self,
        root_concept,
        weight_from_parent: float = 0.0,
        order_from_parent: float = 0.0,
        visited: set[str] | None = None,
    ) -> CalcNode | None:
        if visited is None:
            visited = set()

        qname_str = str(root_concept.qname)
        if qname_str in visited:
            logger.warning("Cycle detected at %s — pruning branch", qname_str)
            return None
        visited.add(qname_str)

        node = CalcNode(
            concept_name=str(root_concept.qname.localName),
            namespace_uri=str(root_concept.qname.namespaceURI),
            namespace_type=classify_namespace(str(root_concept.qname.namespaceURI)),
            label=self.get_label(root_concept),
            weight_from_parent=weight_from_parent,
            order_from_parent=order_from_parent,
        )

        if self.calc_rel_set:
            # NOTE: Arelle API — singular fromModelObject(concept);
            # fromModelObjects() takes no args and returns the full dict.
            rels = self.calc_rel_set.fromModelObject(root_concept)
            for rel in sorted(rels, key=lambda r: getattr(r, "order", 0.0)):
                child = rel.toModelObject
                if child is None:
                    continue
                child_node = self.build_tree(
                    child,
                    weight_from_parent=getattr(rel, "weight", 1.0),
                    order_from_parent=getattr(rel, "order", 0.0),
                    visited=visited.copy(),
                )
                if child_node:
                    node.children.append(child_node)

        return node

    def find_debt_roots(self) -> list:
        if not self.calc_rel_set:
            return []

        roots = []
        seen: set[str] = set()

        for rel in self.calc_rel_set.modelRelationships:
            parent = rel.fromModelObject
            if parent is None:
                continue

            name = str(parent.qname.localName).lower()
            if is_balance_sheet_debt(name):
                qname = str(parent.qname)
                if qname not in seen:
                    seen.add(qname)
                    roots.append(parent)

        roots.sort(key=lambda c: str(c.qname.localName))
        return roots

    def find_concept_by_name(self, name: str):
        name_lower = name.lower()
        for qname_obj, concept in self.model.qnameConcepts.items():
            if str(qname_obj.localName).lower() == name_lower:
                return concept
        return None


def print_calc_tree(node: CalcNode, indent: int = 0, prefix: str = "") -> None:
    weight_str = f" [w={node.weight_from_parent:+.1f}]" if not node.is_root else ""
    label_str = f" — {node.label}" if node.label else ""
    ns_marker = "*" if node.namespace_type == "COMPANY" else " "
    
    line = f"{'  ' * indent}{prefix}{ns_marker} {node.concept_name}{weight_str}{label_str}"
    print(line)

    for i, child in enumerate(node.children):
        is_last = (i == len(node.children) - 1)
        child_prefix = "+-- " if is_last else "+-- "
        print_calc_tree(child, indent + 1, child_prefix)


def tree_to_dict(node: CalcNode) -> dict:
    return {
        "name": node.concept_name,
        "namespace_type": node.namespace_type,
        "weight": node.weight_from_parent,
        "order": node.order_from_parent,
        "label": node.label,
        "children": [tree_to_dict(c) for c in node.children],
    }