"""Tests for detecting relationship-only schema changes."""

from config import SCHEMA_DIR
from schema.graph import SchemaGraph
from schema.schema_types import CalcArc, Concept, SchemaVersion
from schema.version_store import SchemaStore


def test_restatement_detects_relationship_change():
    """
    Simulate: v4 has LongTermDebt -> ComponentA (weight +1.0).
    Restatement: same concepts, but ComponentA now has weight -1.0
    (became a deduction rather than addition).
    
    The diff engine should detect this as a change even though
    no new concepts were introduced.
    """
    # Build synthetic v4-like version
    graph = SchemaGraph()
    graph.add_concept(Concept("LongTermDebt", "http://fasb.org", "STANDARD", None, is_total=True))
    graph.add_concept(Concept("ComponentA", "http://fasb.org", "STANDARD", None, is_component=True))
    graph.add_calc_arc(CalcArc("LongTermDebt", "ComponentA", 1.0, 1.0))
    
    # Simulate: process this as a "filing" to get a baseline
    store = SchemaStore(SCHEMA_DIR)
    # (In real use, you'd compare against the actual prior version)
    
    # Now simulate restatement: same concepts, different weight
    restated = SchemaGraph()
    restated.add_concept(Concept("LongTermDebt", "http://fasb.org", "STANDARD", None, is_total=True))
    restated.add_concept(Concept("ComponentA", "http://fasb.org", "STANDARD", None, is_component=True))
    restated.add_calc_arc(CalcArc("LongTermDebt", "ComponentA", -1.0, 1.0))  # Changed weight!
    
    # The hash should differ because the arc changed
    v_baseline = graph.to_version("test_baseline", None, None, None)
    v_restate = restated.to_version("test_restate", None, None, None)
    
    print(f"Baseline hash: {v_baseline.content_hash}")
    print(f"Restated hash: {v_restate.content_hash}")
    
    assert v_baseline.content_hash != v_restate.content_hash, \
        "Hash should change when calc weight changes"
    
    print("PASS: Relationship-only change detected via hash difference")


def test_same_concepts_different_structure():
    """
    Two filings with identical concept lists but different calc trees
    should produce different versions.
    """
    # Tree A: Debt -> Current + Noncurrent
    graph_a = SchemaGraph()
    graph_a.add_concept(Concept("Debt", "std", "STANDARD", None, is_total=True))
    graph_a.add_concept(Concept("Current", "std", "STANDARD", None, is_component=True))
    graph_a.add_concept(Concept("Noncurrent", "std", "STANDARD", None, is_component=True))
    graph_a.add_calc_arc(CalcArc("Debt", "Current", 1.0, 1.0))
    graph_a.add_calc_arc(CalcArc("Debt", "Noncurrent", 1.0, 2.0))
    
    # Tree B: Debt -> Current only (Noncurrent moved elsewhere)
    graph_b = SchemaGraph()
    graph_b.add_concept(Concept("Debt", "std", "STANDARD", None, is_total=True))
    graph_b.add_concept(Concept("Current", "std", "STANDARD", None, is_component=True))
    graph_b.add_concept(Concept("Noncurrent", "std", "STANDARD", None, is_component=True))
    graph_b.add_calc_arc(CalcArc("Debt", "Current", 1.0, 1.0))
    # Noncurrent arc deliberately omitted
    
    v_a = graph_a.to_version("va", None, None, None)
    v_b = graph_b.to_version("vb", None, None, None)
    
    assert v_a.content_hash != v_b.content_hash, \
        "Different calc trees should have different hashes"
    
    print("PASS: Structural difference detected despite identical concept list")


if __name__ == "__main__":
    test_restatement_detects_relationship_change()
    test_same_concepts_different_structure()
    print("\nRestatement tests passed.")
