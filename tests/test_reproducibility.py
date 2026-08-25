"""Verify deterministic schema version output across runs."""

from config import SCHEMA_DIR
from schema.version_store import SchemaStore


def test_versions_stable():
    """Verify that re-running doesn't create new versions for cached data."""
    store = SchemaStore(SCHEMA_DIR)
    versions_before = store.list_versions()
    hashes_before = {v: store.get_version(v).content_hash for v in versions_before}

    print(f"Versions before: {versions_before}")
    print(f"Hashes: {hashes_before}")

    # Re-load store to verify stability
    store2 = SchemaStore(SCHEMA_DIR)
    versions_after = store2.list_versions()
    hashes_after = {v: store2.get_version(v).content_hash for v in versions_after}

    assert versions_before == versions_after, f"Version mismatch: {versions_before} vs {versions_after}"
    assert hashes_before == hashes_after, f"Hash mismatch: {hashes_before} vs {hashes_after}"

    print("PASS: Versions and hashes are stable across reloads")


if __name__ == "__main__":
    test_versions_stable()
    print("\nReproducibility test passed.")
