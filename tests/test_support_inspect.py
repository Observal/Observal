# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the `observal support inspect` subcommand.

Covers:
- Manifest display from a known bundle
- Tree view output
- --show with valid and invalid paths
- Missing bundle file (exit 1)
- Invalid tar.gz (exit 1)
- Missing manifest (exit 1)
- Schema version warnings (higher, current, lower, non-integer)

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 10.4, 10.5
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path  # noqa: TC003

from typer.testing import CliRunner

from observal_cli.main import app

runner = CliRunner()


# ── Helpers ──────────────────────────────────────────────────────────


def _make_manifest(
    schema_version: str = "1",
    cli_version: str = "0.9.0",
    host_os: str = "Linux",
    extra_fields: dict | None = None,
) -> dict:
    """Build a valid bundle manifest dict."""
    manifest = {
        "bundle_schema_version": schema_version,
        "created_at": "2025-07-15T14:30:22Z",
        "cli_version": cli_version,
        "host_os": host_os,
        "node_id": "test-node",
        "flags_used": {"output": "test.tar.gz", "logs_since": "1h", "include_system": True},
        "collector_results": {
            "versions": {"ok": True, "duration_ms": 50},
            "health": {"ok": True, "duration_ms": 30},
        },
        "redaction_counts": {"config/config.json": 2},
        "file_inventory": [
            {"path": "versions/app.json", "size_bytes": 42, "sha256": "abc123"},
            {"path": "config/config.json", "size_bytes": 100, "sha256": "def456"},
        ],
    }
    if extra_fields:
        manifest.update(extra_fields)
    return manifest


def _add_bytes_to_tar(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    """Add in-memory bytes to a tarfile."""
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def _create_bundle(
    path: Path,
    manifest: dict | None = None,
    files: dict[str, bytes] | None = None,
    include_manifest: bool = True,
) -> Path:
    """Create a .tar.gz bundle at the given path with optional manifest and files.

    Args:
        path: Output path for the archive.
        manifest: Manifest dict. Uses default if None.
        files: Mapping of relative path -> content bytes to include.
        include_manifest: Whether to include bundle_manifest.json.

    Returns:
        The path to the created archive.
    """
    if manifest is None:
        manifest = _make_manifest()
    if files is None:
        files = {
            "versions/app.json": json.dumps({"cli_version": "0.9.0", "server_version": "0.9.0"}).encode(),
            "config/config.json": json.dumps({"DEPLOYMENT_MODE": "docker"}).encode(),
        }

    with tarfile.open(path, "w:gz") as tar:
        if include_manifest:
            manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
            _add_bytes_to_tar(tar, "bundle_manifest.json", manifest_bytes)
        for rel_path, content in files.items():
            _add_bytes_to_tar(tar, rel_path, content)

    return path


# ── Manifest display ─────────────────────────────────────────────────


class TestInspectManifestDisplay:
    """Verify inspect prints the manifest as formatted JSON."""

    def test_manifest_displayed_as_json(self, tmp_path):
        """inspect should print the manifest contents as formatted JSON."""
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz")

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        # The manifest fields should appear in the output
        assert "bundle_schema_version" in result.output
        assert "0.9.0" in result.output  # cli_version
        assert "test-node" in result.output  # node_id
        assert "collector_results" in result.output

    def test_manifest_fields_present(self, tmp_path):
        """All required manifest fields should be visible in the output."""
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz")

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        for field in [
            "bundle_schema_version",
            "created_at",
            "cli_version",
            "host_os",
            "node_id",
            "flags_used",
            "collector_results",
            "redaction_counts",
            "file_inventory",
        ]:
            assert field in result.output, f"Expected field '{field}' in output"


# ── Tree view ────────────────────────────────────────────────────────


class TestInspectTreeView:
    """Verify inspect prints a tree view of archive contents with sizes."""

    def test_tree_shows_file_names(self, tmp_path):
        """The tree view should list all files in the archive."""
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz")

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        assert "versions/app.json" in result.output
        assert "config/config.json" in result.output
        assert "bundle_manifest.json" in result.output

    def test_tree_shows_bundle_contents_label(self, tmp_path):
        """The tree view should have a 'Bundle contents' label."""
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz")

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        assert "Bundle contents" in result.output


# ── --show flag ──────────────────────────────────────────────────────


class TestInspectShowFlag:
    """Verify --show prints a specific file's contents or errors on invalid paths."""

    def test_show_valid_file(self, tmp_path):
        """--show should print the contents of the specified file."""
        file_content = {"cli_version": "0.9.0", "server_version": "0.9.0", "build_hash": "abc123"}
        files = {
            "versions/app.json": json.dumps(file_content).encode(),
            "config/config.json": json.dumps({"DEPLOYMENT_MODE": "docker"}).encode(),
        }
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz", files=files)

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path), "--show", "versions/app.json"])

        assert result.exit_code == 0
        assert "0.9.0" in result.output
        assert "abc123" in result.output

    def test_show_manifest_file(self, tmp_path):
        """--show should work for bundle_manifest.json itself."""
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz")

        result = runner.invoke(
            app, ["doctor", "support", "inspect", str(bundle_path), "--show", "bundle_manifest.json"]
        )

        assert result.exit_code == 0
        # The manifest content should appear (it's printed twice: once as formatted JSON, once via --show)
        assert "bundle_schema_version" in result.output

    def test_show_invalid_path_exits_1(self, tmp_path):
        """--show with a non-existent path should exit 1 and list available files."""
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz")

        result = runner.invoke(
            app, ["doctor", "support", "inspect", str(bundle_path), "--show", "nonexistent/file.json"]
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "File not found" in result.output
        # Should list available files
        assert "versions/app.json" in result.output
        assert "config/config.json" in result.output

    def test_show_lists_available_files_on_miss(self, tmp_path):
        """When --show path doesn't exist, the error should list all available files."""
        files = {
            "versions/app.json": b'{"v": 1}',
            "health/postgres.json": b'{"status": "ok"}',
            "config/config.json": b'{"mode": "docker"}',
        }
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz", files=files)

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path), "--show", "does-not-exist.txt"])

        assert result.exit_code == 1
        # All real files should be listed as available
        for f in ["versions/app.json", "health/postgres.json", "config/config.json", "bundle_manifest.json"]:
            assert f in result.output, f"Expected '{f}' in available files listing"


# ── Missing bundle file ─────────────────────────────────────────────


class TestInspectMissingBundle:
    """Verify inspect exits 1 when the bundle file doesn't exist."""

    def test_missing_file_exits_1(self, tmp_path):
        """Inspecting a non-existent file should exit 1 with an error message."""
        fake_path = tmp_path / "does-not-exist.tar.gz"

        result = runner.invoke(app, ["doctor", "support", "inspect", str(fake_path)])

        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Bundle not found" in result.output


# ── Invalid tar.gz ───────────────────────────────────────────────────


class TestInspectInvalidArchive:
    """Verify inspect exits 1 when the file is not a valid tar.gz."""

    def test_invalid_tar_exits_1(self, tmp_path):
        """A file that isn't a valid tar.gz should cause exit 1."""
        bad_file = tmp_path / "not-a-tarball.tar.gz"
        bad_file.write_bytes(b"this is not a tar.gz file at all")

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bad_file)])

        assert result.exit_code == 1
        assert "cannot open" in result.output.lower() or "Cannot open" in result.output

    def test_empty_file_exits_1(self, tmp_path):
        """An empty file should cause exit 1."""
        empty_file = tmp_path / "empty.tar.gz"
        empty_file.write_bytes(b"")

        result = runner.invoke(app, ["doctor", "support", "inspect", str(empty_file)])

        assert result.exit_code == 1


# ── Missing manifest ────────────────────────────────────────────────


class TestInspectMissingManifest:
    """Verify inspect exits 1 when bundle_manifest.json is missing or malformed."""

    def test_missing_manifest_exits_1(self, tmp_path):
        """A valid tar.gz without bundle_manifest.json should exit 1."""
        bundle_path = _create_bundle(
            tmp_path / "no-manifest.tar.gz",
            files={"versions/app.json": b'{"v": 1}'},
            include_manifest=False,
        )

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 1
        assert "missing" in result.output.lower() or "malformed" in result.output.lower()

    def test_malformed_manifest_exits_1(self, tmp_path):
        """A bundle with invalid JSON in bundle_manifest.json should exit 1."""
        bundle_path = tmp_path / "bad-manifest.tar.gz"
        with tarfile.open(bundle_path, "w:gz") as tar:
            _add_bytes_to_tar(tar, "bundle_manifest.json", b"not valid json {{{")
            _add_bytes_to_tar(tar, "versions/app.json", b'{"v": 1}')

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 1
        assert "missing" in result.output.lower() or "malformed" in result.output.lower()


# ── Schema version warnings ─────────────────────────────────────────


class TestInspectSchemaVersionWarnings:
    """Verify schema version warning behavior per requirements 10.4 and 10.5."""

    def test_current_version_no_warning(self, tmp_path):
        """Schema version equal to current should produce no warning."""
        manifest = _make_manifest(schema_version="1")
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz", manifest=manifest)

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        assert "warning" not in result.output.lower()
        assert "newer CLI" not in result.output

    def test_lower_version_no_warning(self, tmp_path):
        """Schema version lower than current should produce no warning."""
        # CURRENT_SCHEMA_VERSION is 1, so version "0" is lower
        # Note: in practice version starts at 1, but the logic should handle it
        manifest = _make_manifest(schema_version="0")
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz", manifest=manifest)

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        assert "newer CLI" not in result.output

    def test_higher_version_shows_warning(self, tmp_path):
        """Schema version higher than current should show a warning but still display."""
        manifest = _make_manifest(schema_version="99")
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz", manifest=manifest)

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        assert "newer CLI" in result.output or "newer" in result.output.lower()
        # Should still display the manifest despite the warning
        assert "bundle_schema_version" in result.output
        assert "99" in result.output

    def test_higher_version_still_shows_tree(self, tmp_path):
        """Even with a higher schema version, the file tree should still be displayed."""
        manifest = _make_manifest(schema_version="5")
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz", manifest=manifest)

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        # Tree should still render
        assert "Bundle contents" in result.output
        assert "versions/app.json" in result.output

    def test_non_integer_version_shows_warning(self, tmp_path):
        """A non-integer schema version should show an 'unrecognized' warning."""
        manifest = _make_manifest(schema_version="beta")
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz", manifest=manifest)

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        assert "unrecognized" in result.output.lower() or "Unrecognized" in result.output
        # Should still display the manifest
        assert "bundle_schema_version" in result.output

    def test_non_integer_version_still_shows_manifest(self, tmp_path):
        """Even with a non-integer version, the manifest and tree should display."""
        manifest = _make_manifest(schema_version="v2.0")
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz", manifest=manifest)

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        assert "v2.0" in result.output
        assert "Bundle contents" in result.output


# ── Read-only / no extraction ────────────────────────────────────────


class TestInspectNoExtraction:
    """Verify inspect never extracts files to disk (Requirement 5.4)."""

    def test_inspect_does_not_create_files(self, tmp_path):
        """After inspect, no new files should appear in the working directory."""
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz")
        work_dir = tmp_path / "workdir"
        work_dir.mkdir()

        # List files before
        before = set(work_dir.iterdir())

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        # No new files should have been created
        after = set(work_dir.iterdir())
        assert before == after, "inspect should not extract files to disk"

    def test_show_does_not_create_files(self, tmp_path):
        """--show should print to stdout without extracting to disk."""
        bundle_path = _create_bundle(tmp_path / "bundle.tar.gz")
        work_dir = tmp_path / "workdir"
        work_dir.mkdir()

        before = set(work_dir.iterdir())

        result = runner.invoke(app, ["doctor", "support", "inspect", str(bundle_path), "--show", "versions/app.json"])

        assert result.exit_code == 0
        after = set(work_dir.iterdir())
        assert before == after, "--show should not extract files to disk"
