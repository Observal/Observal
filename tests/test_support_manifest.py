# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the support bundle manifest module."""

import hashlib
import json

from observal_cli.support.manifest import (
    BundleManifest,
    FileEntry,
    compute_file_entry,
)

# --- FileEntry ---


class TestFileEntry:
    def test_creation(self):
        entry = FileEntry(path="versions/app.json", size_bytes=128, sha256="abc123")
        assert entry.path == "versions/app.json"
        assert entry.size_bytes == 128
        assert entry.sha256 == "abc123"

    def test_fields_are_accessible(self):
        entry = FileEntry(path="config/config.json", size_bytes=0, sha256="e3b0c44298fc1c149afbf4c8996fb924")
        assert entry.path == "config/config.json"
        assert entry.size_bytes == 0
        assert entry.sha256 == "e3b0c44298fc1c149afbf4c8996fb924"


# --- BundleManifest creation ---


class TestBundleManifestCreation:
    def test_defaults(self):
        m = BundleManifest()
        assert m.bundle_schema_version == "1"
        assert m.created_at == ""
        assert m.cli_version == ""
        assert m.host_os == ""
        assert m.node_id == ""
        assert m.flags_used == {}
        assert m.collector_results == {}
        assert m.redaction_counts == {}
        assert m.file_inventory == []

    def test_all_fields(self):
        entry = FileEntry(path="versions/app.json", size_bytes=42, sha256="deadbeef")
        m = BundleManifest(
            bundle_schema_version="1",
            created_at="2025-07-15T14:30:22Z",
            cli_version="0.9.0",
            host_os="Linux",
            node_id="prod-node-01",
            flags_used={"include_system": True, "logs_since": "1h"},
            collector_results={"versions_app": {"ok": True, "duration_ms": 50}},
            redaction_counts={"config/config.json": 3},
            file_inventory=[entry],
        )
        assert m.bundle_schema_version == "1"
        assert m.created_at == "2025-07-15T14:30:22Z"
        assert m.cli_version == "0.9.0"
        assert m.host_os == "Linux"
        assert m.node_id == "prod-node-01"
        assert m.flags_used == {"include_system": True, "logs_since": "1h"}
        assert m.collector_results == {"versions_app": {"ok": True, "duration_ms": 50}}
        assert m.redaction_counts == {"config/config.json": 3}
        assert len(m.file_inventory) == 1
        assert m.file_inventory[0].path == "versions/app.json"

    def test_node_id_defaults_to_empty_string(self):
        m = BundleManifest()
        assert m.node_id == ""

    def test_node_id_can_be_set(self):
        m = BundleManifest(node_id="my-hostname")
        assert m.node_id == "my-hostname"


# --- to_dict ---


class TestToDict:
    def test_empty_manifest(self):
        m = BundleManifest()
        d = m.to_dict()
        assert d["bundle_schema_version"] == "1"
        assert d["created_at"] == ""
        assert d["cli_version"] == ""
        assert d["host_os"] == ""
        assert d["node_id"] == ""
        assert d["flags_used"] == {}
        assert d["collector_results"] == {}
        assert d["redaction_counts"] == {}
        assert d["file_inventory"] == []

    def test_with_file_inventory(self):
        m = BundleManifest(
            file_inventory=[
                FileEntry(path="a.json", size_bytes=10, sha256="aaa"),
                FileEntry(path="b.json", size_bytes=20, sha256="bbb"),
            ]
        )
        d = m.to_dict()
        assert len(d["file_inventory"]) == 2
        assert d["file_inventory"][0] == {"path": "a.json", "size_bytes": 10, "sha256": "aaa"}
        assert d["file_inventory"][1] == {"path": "b.json", "size_bytes": 20, "sha256": "bbb"}

    def test_node_id_in_dict(self):
        m = BundleManifest(node_id="worker-3")
        d = m.to_dict()
        assert d["node_id"] == "worker-3"

    def test_all_fields_present(self):
        m = BundleManifest(
            bundle_schema_version="1",
            created_at="2025-07-15T14:30:22Z",
            cli_version="0.9.0",
            host_os="Linux",
            node_id="prod-node-01",
            flags_used={"include_system": True},
            collector_results={"health_pg": {"ok": True, "duration_ms": 12}},
            redaction_counts={"config/config.json": 5},
            file_inventory=[FileEntry(path="f.json", size_bytes=99, sha256="fff")],
        )
        d = m.to_dict()
        expected_keys = {
            "bundle_schema_version",
            "created_at",
            "cli_version",
            "host_os",
            "node_id",
            "flags_used",
            "collector_results",
            "redaction_counts",
            "file_inventory",
        }
        assert set(d.keys()) == expected_keys


# --- from_dict ---


class TestFromDict:
    def test_empty_dict(self):
        m = BundleManifest.from_dict({})
        assert m.bundle_schema_version == "1"
        assert m.created_at == ""
        assert m.cli_version == ""
        assert m.host_os == ""
        assert m.node_id == ""
        assert m.flags_used == {}
        assert m.collector_results == {}
        assert m.redaction_counts == {}
        assert m.file_inventory == []

    def test_full_dict(self):
        data = {
            "bundle_schema_version": "1",
            "created_at": "2025-07-15T14:30:22Z",
            "cli_version": "0.9.0",
            "host_os": "Linux",
            "node_id": "prod-node-01",
            "flags_used": {"include_system": True, "logs_since": "2h"},
            "collector_results": {"versions_app": {"ok": True, "duration_ms": 50}},
            "redaction_counts": {"config/config.json": 3},
            "file_inventory": [
                {"path": "versions/app.json", "size_bytes": 42, "sha256": "deadbeef"},
            ],
        }
        m = BundleManifest.from_dict(data)
        assert m.bundle_schema_version == "1"
        assert m.created_at == "2025-07-15T14:30:22Z"
        assert m.cli_version == "0.9.0"
        assert m.host_os == "Linux"
        assert m.node_id == "prod-node-01"
        assert m.flags_used == {"include_system": True, "logs_since": "2h"}
        assert m.collector_results == {"versions_app": {"ok": True, "duration_ms": 50}}
        assert m.redaction_counts == {"config/config.json": 3}
        assert len(m.file_inventory) == 1
        assert m.file_inventory[0].path == "versions/app.json"
        assert m.file_inventory[0].size_bytes == 42
        assert m.file_inventory[0].sha256 == "deadbeef"

    def test_missing_optional_fields_use_defaults(self):
        data = {"bundle_schema_version": "2"}
        m = BundleManifest.from_dict(data)
        assert m.bundle_schema_version == "2"
        assert m.node_id == ""
        assert m.file_inventory == []

    def test_node_id_round_trips(self):
        data = {"node_id": "my-host-name"}
        m = BundleManifest.from_dict(data)
        assert m.node_id == "my-host-name"

    def test_multiple_file_inventory_entries(self):
        data = {
            "file_inventory": [
                {"path": "a.json", "size_bytes": 10, "sha256": "aaa"},
                {"path": "b.json", "size_bytes": 20, "sha256": "bbb"},
                {"path": "c.json", "size_bytes": 30, "sha256": "ccc"},
            ]
        }
        m = BundleManifest.from_dict(data)
        assert len(m.file_inventory) == 3
        assert m.file_inventory[2].path == "c.json"


# --- to_json ---


class TestToJson:
    def test_output_is_valid_json(self):
        m = BundleManifest(
            created_at="2025-07-15T14:30:22Z",
            cli_version="0.9.0",
            host_os="Linux",
            node_id="test-node",
        )
        json_str = m.to_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_json_contains_all_keys(self):
        m = BundleManifest()
        parsed = json.loads(m.to_json())
        expected_keys = {
            "bundle_schema_version",
            "created_at",
            "cli_version",
            "host_os",
            "node_id",
            "flags_used",
            "collector_results",
            "redaction_counts",
            "file_inventory",
        }
        assert set(parsed.keys()) == expected_keys

    def test_json_is_indented(self):
        m = BundleManifest()
        json_str = m.to_json()
        # json.dumps with indent=2 produces newlines
        assert "\n" in json_str

    def test_json_with_file_inventory(self):
        m = BundleManifest(file_inventory=[FileEntry(path="test.json", size_bytes=100, sha256="abc")])
        parsed = json.loads(m.to_json())
        assert len(parsed["file_inventory"]) == 1
        assert parsed["file_inventory"][0]["path"] == "test.json"


# --- JSON round-trip ---


class TestJsonRoundTrip:
    def test_empty_manifest_round_trip(self):
        original = BundleManifest()
        restored = BundleManifest.from_dict(json.loads(original.to_json()))
        assert restored.to_dict() == original.to_dict()

    def test_full_manifest_round_trip(self):
        original = BundleManifest(
            bundle_schema_version="1",
            created_at="2025-07-15T14:30:22Z",
            cli_version="0.9.0",
            host_os="Linux",
            node_id="prod-node-01",
            flags_used={"include_system": True, "logs_since": "1h"},
            collector_results={
                "versions_app": {"ok": True, "duration_ms": 50},
                "health_pg": {"ok": False, "duration_ms": 10000, "error": "timeout"},
            },
            redaction_counts={"config/config.json": 3, "logs/recent.ndjson": 7},
            file_inventory=[
                FileEntry(path="versions/app.json", size_bytes=42, sha256="deadbeef"),
                FileEntry(path="config/config.json", size_bytes=256, sha256="cafebabe"),
            ],
        )
        json_str = original.to_json()
        restored = BundleManifest.from_dict(json.loads(json_str))
        assert restored.to_dict() == original.to_dict()

    def test_round_trip_preserves_node_id(self):
        original = BundleManifest(node_id="special-host-name")
        restored = BundleManifest.from_dict(json.loads(original.to_json()))
        assert restored.node_id == "special-host-name"

    def test_round_trip_preserves_file_inventory_order(self):
        entries = [FileEntry(path=f"file_{i}.json", size_bytes=i * 10, sha256=f"hash_{i}") for i in range(5)]
        original = BundleManifest(file_inventory=entries)
        restored = BundleManifest.from_dict(json.loads(original.to_json()))
        for i, entry in enumerate(restored.file_inventory):
            assert entry.path == f"file_{i}.json"
            assert entry.size_bytes == i * 10
            assert entry.sha256 == f"hash_{i}"


# --- compute_file_entry ---


class TestComputeFileEntry:
    def test_correct_sha256(self):
        content = b"hello world"
        expected_hash = hashlib.sha256(content).hexdigest()
        entry = compute_file_entry("test.txt", content)
        assert entry.sha256 == expected_hash

    def test_correct_size(self):
        content = b"some content here"
        entry = compute_file_entry("test.txt", content)
        assert entry.size_bytes == len(content)

    def test_correct_path(self):
        entry = compute_file_entry("versions/app.json", b"{}")
        assert entry.path == "versions/app.json"

    def test_empty_content(self):
        content = b""
        expected_hash = hashlib.sha256(content).hexdigest()
        entry = compute_file_entry("empty.txt", content)
        assert entry.size_bytes == 0
        assert entry.sha256 == expected_hash

    def test_binary_content(self):
        content = bytes(range(256))
        expected_hash = hashlib.sha256(content).hexdigest()
        entry = compute_file_entry("binary.bin", content)
        assert entry.size_bytes == 256
        assert entry.sha256 == expected_hash

    def test_returns_file_entry_instance(self):
        entry = compute_file_entry("test.txt", b"data")
        assert isinstance(entry, FileEntry)

    def test_known_hash_value(self):
        # SHA-256 of empty bytes is a well-known constant
        content = b""
        entry = compute_file_entry("empty", content)
        assert entry.sha256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
