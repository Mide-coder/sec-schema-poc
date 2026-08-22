#!/usr/bin/env python3
"""
test_amendments.py

Synthetic amendment tests.
Validates amendment detection, force-new-version, and parent linking.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from schema.version_store import SchemaStore
from schema.graph import SchemaGraph
from schema.schema_types import SchemaVersion, Concept, CalcArc
from pipeline.process_filing import is_amendment, find_original_version

SCHEMA_DIR = Path(__file__).parent.parent / "schema_versions"


def test_is_amendment_detection():
    """Rule 8: Amendments are detected by form type ending in /A."""
    assert is_amendment("0001144879-22-000043", "10-K/A") is True
    assert is_amendment("0001144879-22-000043", "10-Q/A") is True
    assert is_amendment("0001144879-22-000043", "8-K/A") is True
    assert is_amendment("0001144879-22-000043", "10-K") is False
    assert is_amendment("0001144879-22-000043", "10-Q") is False
    assert is_amendment("0001144879-22-000043", "8-K") is False
    assert is_amendment("0001144879-22-000043", None) is False
    print("PASS: test_is_amendment_detection")


def test_find_original_version():
    """Rule 10: Amendment parent points to original filing's version."""
    store = SchemaStore(SCHEMA_DIR)

    # Find any version that has a source_filing (not baseline)
    versions_with_source = [
        vid for vid in store.list_versions()
        if store.get_version(vid) and store.get_version(vid).source_filing
    ]
    assert len(versions_with_source) > 0, "Need at least one version with source_filing"

    # Pick the first one and test find_original_version with /A suffix
    target_vid = versions_with_source[0]
    target = store.get_version(target_vid)
    accession = target.source_filing

    found = find_original_version(store, accession + "/A")
    assert found == target_vid, f"Expected {target_vid}, got {found}"
    print("PASS: test_find_original_version")


def test_amendment_always_creates_version():
    """Rule 9: Amendment always creates a new version, even with identical content."""
    store = SchemaStore(SCHEMA_DIR)

    # Get any version's graph and create a force_new version from it
    versions = store.list_versions()
    assert len(versions) >= 2, "Need at least 2 versions for this test"

    # Use the last real version
    latest_vid = versions[-1]
    latest = store.get_version(latest_vid)
    graph = SchemaGraph.from_version(latest)

    # With force_new, it MUST create a new version even with same hash
    result_forced = store.create_version(
        graph=graph,
        source_filing="test-amendment-synthetic",
        taxonomy_year="2025",
        force_new=True,
    )
    assert result_forced.version_id != latest_vid, \
        f"Expected new version, got {result_forced.version_id}"
    assert result_forced.content_hash == latest.content_hash, \
        "Amendment version should have same hash as original"
    print("PASS: test_amendment_always_creates_version")


def test_force_new_bypasses_hash_dedup():
    """force_new=True in create_version skips the no-op hash check."""
    store = SchemaStore(SCHEMA_DIR)

    # Get any existing version's graph
    v0 = store.get_version("v0")
    graph = SchemaGraph.from_version(v0)

    # Without force_new, creating from identical graph returns existing version (no-op)
    result_normal = store.create_version(
        graph=graph,
        source_filing="test-normal",
        taxonomy_year="2025",
    )
    # Should return an existing version, not create a new one
    assert result_normal.version_id == "v0", \
        f"Expected no-op (v0), got new {result_normal.version_id}"

    # With force_new, it MUST create a new version even with same hash
    result_forced = store.create_version(
        graph=graph,
        source_filing="test-forced",
        taxonomy_year="2025",
        force_new=True,
    )
    assert result_forced.version_id != "v0", \
        f"Expected new version, got {result_forced.version_id}"
    print("PASS: test_force_new_bypasses_hash_dedup")


def test_amendment_parent_version_override():
    """Amendments can specify a custom parent_version_id."""
    store = SchemaStore(SCHEMA_DIR)

    versions = store.list_versions()
    latest_vid = versions[-1]
    latest = store.get_version(latest_vid)
    graph = SchemaGraph.from_version(latest)

    # Create with explicit parent
    result = store.create_version(
        graph=graph,
        source_filing="test-parent-override",
        taxonomy_year="2025",
        force_new=True,
        parent_version_id=latest_vid,
    )
    assert result.parent_version_id == latest_vid, \
        f"Expected parent {latest_vid}, got {result.parent_version_id}"
    print("PASS: test_amendment_parent_version_override")


def test_amendment_version_has_correct_source():
    """The amendment version's source_filing is the amendment's accession number."""
    store = SchemaStore(SCHEMA_DIR)

    versions = store.list_versions()
    latest_vid = versions[-1]
    latest = store.get_version(latest_vid)
    graph = SchemaGraph.from_version(latest)

    result = store.create_version(
        graph=graph,
        source_filing="test-source-check",
        taxonomy_year="2025",
        force_new=True,
    )
    assert result.source_filing == "test-source-check", \
        f"Expected source 'test-source-check', got {result.source_filing}"
    print("PASS: test_amendment_version_has_correct_source")


if __name__ == "__main__":
    test_is_amendment_detection()
    test_find_original_version()
    test_amendment_always_creates_version()
    test_force_new_bypasses_hash_dedup()
    test_amendment_parent_version_override()
    test_amendment_version_has_correct_source()
    print("\n=== All amendment tests passed ===")
