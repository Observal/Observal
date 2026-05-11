# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Bundle manifest schema and file inventory builder.

Defines the BundleManifest and FileEntry dataclasses used to describe
the contents of a support bundle archive. Every file in the archive
is recorded in the manifest with its path, size, and SHA-256 hash.
"""

import hashlib
import json
from dataclasses import dataclass, field


@dataclass
class FileEntry:
    path: str
    size_bytes: int
    sha256: str


@dataclass
class BundleManifest:
    bundle_schema_version: str = "1"
    created_at: str = ""
    cli_version: str = ""
    host_os: str = ""
    node_id: str = ""  # socket.gethostname() — identifies which machine produced this bundle
    flags_used: dict = field(default_factory=dict)
    collector_results: dict = field(default_factory=dict)
    redaction_counts: dict = field(default_factory=dict)
    file_inventory: list[FileEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "bundle_schema_version": self.bundle_schema_version,
            "created_at": self.created_at,
            "cli_version": self.cli_version,
            "host_os": self.host_os,
            "node_id": self.node_id,
            "flags_used": self.flags_used,
            "collector_results": self.collector_results,
            "redaction_counts": self.redaction_counts,
            "file_inventory": [
                {"path": f.path, "size_bytes": f.size_bytes, "sha256": f.sha256} for f in self.file_inventory
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BundleManifest":
        inventory = [
            FileEntry(path=f["path"], size_bytes=f["size_bytes"], sha256=f["sha256"])
            for f in data.get("file_inventory", [])
        ]
        return cls(
            bundle_schema_version=data.get("bundle_schema_version", "1"),
            created_at=data.get("created_at", ""),
            cli_version=data.get("cli_version", ""),
            host_os=data.get("host_os", ""),
            node_id=data.get("node_id", ""),
            flags_used=data.get("flags_used", {}),
            collector_results=data.get("collector_results", {}),
            redaction_counts=data.get("redaction_counts", {}),
            file_inventory=inventory,
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def compute_file_entry(path: str, content: bytes) -> FileEntry:
    """Compute a FileEntry with SHA-256 hash for a file's content."""
    return FileEntry(
        path=path,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
