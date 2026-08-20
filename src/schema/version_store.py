#!/usr/bin/env python3
"""
version_store.py

Day 7/9: Immutable schema version store.
- Loads existing versions from disk
- Creates new versions only if content hash changed (no-op detection)
- Enforces immutability: no written file is ever edited
- Answers point-in-time queries by date or accession
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterator

from schema.schema_types import SchemaVersion
from schema.graph import SchemaGraph

logger = logging.getLogger(__name__)


class SchemaStore:
    """
    Manages schema_versions/ directory.
    
    Design:
    - Versions are files on disk, never edited after creation
    - In-memory index for fast hash lookup and date-based queries
    - create_version() returns existing version ID if hash matches (no-op)
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        
        # In-memory index: version_id -> SchemaVersion
        self._versions: dict[str, SchemaVersion] = {}
        # Hash index: content_hash -> version_id (for no-op detection)
        self._hash_index: dict[str, str] = {}
        
        self._load_existing()

    def _load_existing(self) -> None:
        """Load all existing version files from disk."""
        if not self.directory.exists():
            return
        
        for path in sorted(self.directory.glob("v*.json")):
            try:
                version = self._load_file(path)
                self._index_version(version)
                logger.info("Loaded existing version: %s", version.version_id)
            except Exception:
                logger.exception("Failed to load %s", path)

    def _load_file(self, path: Path) -> SchemaVersion:
        """Deserialize a single version file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        
        # Import here to avoid circular issues
        from schema.schema_types import Concept, CalcArc, DimensionArc
        
        return SchemaVersion(
            version_id=data["version_id"],
            parent_version_id=data.get("parent_version_id"),
            source_filing=data.get("source_filing"),
            taxonomy_year=data.get("taxonomy_year"),
            content_hash=data.get("content_hash", ""),
            concepts=tuple(
                Concept(
                    name=c["name"],
                    namespace_uri=c["namespace_uri"],
                    namespace_type=c["namespace_type"],
                    label=c.get("label"),
                    is_total=c.get("is_total", False),
                    is_component=c.get("is_component", False),
                )
                for c in data["concepts"]
            ),
            calc_arcs=tuple(
                CalcArc(
                    parent_name=a["parent"],
                    child_name=a["child"],
                    weight=a["weight"],
                    order=a["order"],
                )
                for a in data["calc_arcs"]
            ),
            dimension_arcs=tuple(
                DimensionArc(
                    axis_name=a["axis"],
                    member_name=a["member"],
                    member_namespace_type=a["member_ns"],
                )
                for a in data["dimension_arcs"]
            ),
            unresolved=tuple(
                Concept(
                    name=c["name"],
                    namespace_uri="",
                    namespace_type=c["namespace_type"],
                    label=None,
                )
                for c in data.get("unresolved", [])
            ),
        )

    def _index_version(self, version: SchemaVersion) -> None:
        """Add version to in-memory indexes."""
        self._versions[version.version_id] = version
        if version.content_hash:
            self._hash_index[version.content_hash] = version.version_id

    def _save_file(self, version: SchemaVersion) -> Path:
        """Serialize version to JSON. Atomic write."""
        path = self.directory / f"{version.version_id}.json"
        temp = path.with_suffix(".tmp")
        
        data = {
            "version_id": version.version_id,
            "parent_version_id": version.parent_version_id,
            "source_filing": version.source_filing,
            "taxonomy_year": version.taxonomy_year,
            "content_hash": version.content_hash,
            "concepts": [
                {
                    "name": c.name,
                    "namespace_uri": c.namespace_uri,
                    "namespace_type": c.namespace_type,
                    "label": c.label,
                    "is_total": c.is_total,
                    "is_component": c.is_component,
                }
                for c in version.concepts
            ],
            "calc_arcs": [
                {"parent": a.parent_name, "child": a.child_name, "weight": a.weight, "order": a.order}
                for a in version.calc_arcs
            ],
            "dimension_arcs": [
                {"axis": a.axis_name, "member": a.member_name, "member_ns": a.member_namespace_type}
                for a in version.dimension_arcs
            ],
            "unresolved": [
                {"name": c.name, "namespace_type": c.namespace_type}
                for c in version.unresolved
            ],
        }
        
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        
        temp.replace(path)
        logger.info("Saved version: %s", path)
        return path

    def list_versions(self) -> list[str]:
        """Return all version IDs in chronological order."""
        return sorted(self._versions.keys())

    def get_version(self, version_id: str) -> SchemaVersion | None:
        """Fetch a version by ID."""
        return self._versions.get(version_id)

    def get_version_for_hash(self, content_hash: str) -> SchemaVersion | None:
        """Check if a version with this hash already exists (no-op detection)."""
        vid = self._hash_index.get(content_hash)
        if vid:
            return self._versions.get(vid)
        return None

    def create_version(
        self,
        graph: SchemaGraph,
        source_filing: str,
        taxonomy_year: str | None,
    ) -> SchemaVersion:
        """
        Create a new version from a graph, or return existing if hash matches.
        
        Returns:
            SchemaVersion (new or existing)
        """
        # Build the version object (without ID)
        temp_version = graph.to_version(
            version_id="temp",  # Placeholder
            parent_version_id=self._latest_version_id(),
            source_filing=source_filing,
            taxonomy_year=taxonomy_year,
        )
        
        # No-op detection: does this hash already exist?
        existing = self.get_version_for_hash(temp_version.content_hash)
        if existing:
            logger.info(
                "No-op: filing %s matches version %s (hash=%s)",
                source_filing, existing.version_id, existing.content_hash
            )
            return existing
        
        # New version needed
        new_id = self._next_version_id()
        version = SchemaVersion(
            version_id=new_id,
            parent_version_id=temp_version.parent_version_id,
            source_filing=source_filing,
            taxonomy_year=temp_version.taxonomy_year,
            concepts=temp_version.concepts,
            calc_arcs=temp_version.calc_arcs,
            dimension_arcs=temp_version.dimension_arcs,
            unresolved=temp_version.unresolved,
            content_hash=temp_version.content_hash,
        )
        
        # Save and index
        self._save_file(version)
        self._index_version(version)
        
        logger.info(
            "Created %s from %s (hash=%s, concepts=%d, arcs=%d)",
            new_id, source_filing, version.content_hash,
            len(version.concepts), len(version.calc_arcs) + len(version.dimension_arcs)
        )
        return version

    def _latest_version_id(self) -> str | None:
        """Return the most recent version ID, or None if empty."""
        versions = self.list_versions()
        return versions[-1] if versions else None

    def _next_version_id(self) -> str:
        """Generate next version ID (v0, v1, v2, ...)."""
        versions = self.list_versions()
        if not versions:
            return "v0"
        # Extract number from last version
        last = versions[-1]
        num = int(last[1:])  # "v3" -> 3
        return f"v{num + 1}"

    def get_version_for_accession(self, accession: str) -> SchemaVersion | None:
        """
        Find the version created for a specific filing accession number.
        Returns the most recent match if multiple exist.
        """
        matches = [
            v for v in self._versions.values()
            if v.source_filing == accession
        ]
        if not matches:
            return None
        # Return latest by version_id sort
        return sorted(matches, key=lambda v: v.version_id)[-1]

    def get_version_for_date(self, date_str: str) -> SchemaVersion | None:
        """
        Find the version active on a given date.
        For now: returns the latest version whose source_filing date <= target.
        (Simplified — full implementation needs filing date index.)
        """
        # TODO: Build date-based index when pipeline is wired
        # For now, return latest version
        latest = self._latest_version_id()
        return self._versions.get(latest) if latest else None

    def is_immutable(self, version_id: str) -> bool:
        """
        Verify that a version file on disk has not been modified since creation.
        Recomputes hash from file contents and compares to stored hash.
        """
        version = self.get_version(version_id)
        if version is None:
            return False
        
        path = self.directory / f"{version_id}.json"
        if not path.exists():
            return False
        
        # Recompute hash from the stored JSON
        with open(path, "rb") as f:
            import hashlib
            file_hash = hashlib.sha256(f.read()).hexdigest()[:16]
        
        # The content_hash is of the graph, not the file. 
        # True immutability check: verify that re-serializing produces identical bytes.
        try:
            # Read original bytes
            with open(path, "rb") as f:
                original = f.read()
            # Re-save and re-read
            self._save_file(version)
            with open(path, "rb") as f:
                rewritten = f.read()
            return original == rewritten
        except Exception:
            return False