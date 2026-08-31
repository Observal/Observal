# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for support bundle wiring: CLI registration, directory structure, and failure handling.

Covers:
- support_app is registered on the root Typer app as 'support'
- bundle subcommand produces correct directory structure
- Partial failure: individual collector failures still produce a valid bundle (exit 0)
- Total failure: when no data can be collected, exit with code 1
"""

from __future__ import annotations

import json
import re
import tarfile
from unittest.mock import patch

from typer.testing import CliRunner

from observal_cli.errors import CliError, ErrorCategory
from observal_cli.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _unavailable() -> CliError:
    return CliError(
        ErrorCategory.UNAVAILABLE,
        "Server unavailable.",
        operation="Generate support bundle",
        resource="support endpoint",
    )


# ── CLI registration ─────────────────────────────────────────────────


class TestSupportAppRegistration:
    """Verify support_app is wired into the root Typer app."""

    def test_support_group_exists(self):
        """The 'support' subgroup should appear in the root app."""
        result = runner.invoke(app, ["doctor", "support", "--help"])
        assert result.exit_code == 0
        output = _ANSI_RE.sub("", result.output)
        assert "bundle" in output
        assert "inspect" in output

    def test_support_bundle_help(self):
        """The 'bundle' subcommand should be accessible."""
        result = runner.invoke(app, ["doctor", "support", "bundle", "--help"])
        assert result.exit_code == 0
        output = _ANSI_RE.sub("", result.output)
        assert "--file" in output
        assert "--output" in output
        assert "--logs-since" in output
        assert "--include-system" in output

    def test_support_help_mentions_no_customer_data(self):
        """The support group help should mention no customer data."""
        result = runner.invoke(app, ["doctor", "support", "--help"])
        assert result.exit_code == 0
        output = _ANSI_RE.sub("", result.output).lower()
        assert "no customer data" in output


# ── Directory structure ──────────────────────────────────────────────


def _make_server_response(
    versions_ok=True,
    health_ok=True,
    config_ok=True,
):
    """Build a mock server response with controllable collector success."""
    collectors = {}

    if versions_ok:
        collectors["versions"] = {
            "ok": True,
            "duration_ms": 50,
            "data": {
                "app_version": "0.9.0",
                "alembic_revision": "abc123",
                "clickhouse_version": "24.1",
                "clickhouse_tables": ["traces", "spans"],
            },
        }
    else:
        collectors["versions"] = {
            "ok": False,
            "duration_ms": 10000,
            "data": None,
            "error": "Collector timed out",
        }

    if health_ok:
        collectors["health"] = {
            "ok": True,
            "duration_ms": 30,
            "data": {
                "postgres": {"status": "ok", "latency_ms": 5},
                "clickhouse": {"status": "ok", "latency_ms": 8},
                "redis": {"status": "ok", "latency_ms": 2},
            },
        }
    else:
        collectors["health"] = {
            "ok": False,
            "duration_ms": 10000,
            "data": None,
            "error": "Health check failed",
        }

    if config_ok:
        collectors["config"] = {
            "ok": True,
            "duration_ms": 10,
            "data": {
                "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/db",
                "REDIS_URL": "redis://localhost:6379",
                "SECRET_KEY": "should-be-filtered-out",
                "DEPLOYMENT_MODE": "docker",
            },
        }
    else:
        collectors["config"] = {
            "ok": False,
            "duration_ms": 10000,
            "data": None,
            "error": "Config collection failed",
        }

    return {"server_version": "0.9.0", "collectors": collectors}


class TestBundleDirectoryStructure:
    """Verify the bundle archive contains the expected directory structure."""

    def test_bundle_contains_expected_directories(self, tmp_path):
        """Bundle should contain versions/, health/, system/, config/, and bundle_manifest.json."""
        output_path = tmp_path / "test-bundle.tar.gz"
        server_resp = _make_server_response()

        with (
            patch("observal_cli.cmd_support.client.post", return_value=server_resp),
        ):
            result = runner.invoke(app, ["doctor", "support", "bundle", "--file", str(output_path)])

        assert result.exit_code == 0, f"Unexpected exit code: {result.output}"
        assert output_path.exists()

        with tarfile.open(output_path, "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]

        # Check required files/directories
        assert "bundle_manifest.json" in names

        # Check versions directory files
        version_files = [n for n in names if n.startswith("versions/")]
        assert len(version_files) > 0, "Should have files in versions/"

        # Check health directory files
        health_files = [n for n in names if n.startswith("health/")]
        assert len(health_files) > 0, "Should have files in health/"

        # Check config directory files
        config_files = [n for n in names if n.startswith("config/")]
        assert len(config_files) > 0, "Should have files in config/"

        # Check system directory files (default --include-system)
        system_files = [n for n in names if n.startswith("system/")]
        assert len(system_files) > 0, "Should have files in system/ by default"

    def test_bundle_manifest_is_valid_json(self, tmp_path):
        """bundle_manifest.json should be valid JSON with required fields."""
        output_path = tmp_path / "test-bundle.tar.gz"
        server_resp = _make_server_response()

        with (
            patch("observal_cli.cmd_support.client.post", return_value=server_resp),
        ):
            result = runner.invoke(app, ["doctor", "support", "bundle", "--file", str(output_path)])

        assert result.exit_code == 0

        with tarfile.open(output_path, "r:gz") as tar:
            manifest_member = tar.getmember("bundle_manifest.json")
            manifest_data = json.loads(tar.extractfile(manifest_member).read())

        assert "bundle_schema_version" in manifest_data
        assert "created_at" in manifest_data
        assert "cli_version" in manifest_data
        assert "host_os" in manifest_data
        assert "node_id" in manifest_data
        assert "flags_used" in manifest_data
        assert "collector_results" in manifest_data
        assert "redaction_counts" in manifest_data
        assert "file_inventory" in manifest_data

    def test_bundle_no_system_when_flag_disabled(self, tmp_path):
        """With --no-include-system, system/ directory should be absent."""
        output_path = tmp_path / "test-bundle.tar.gz"
        server_resp = _make_server_response()

        with (
            patch("observal_cli.cmd_support.client.post", return_value=server_resp),
        ):
            result = runner.invoke(
                app,
                ["doctor", "support", "bundle", "--file", str(output_path), "--no-include-system"],
            )

        assert result.exit_code == 0

        with tarfile.open(output_path, "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]

        system_files = [n for n in names if n.startswith("system/")]
        assert len(system_files) == 0, "system/ should not be present with --no-include-system"


# ── Partial failure handling ─────────────────────────────────────────


class TestPartialFailure:
    """Individual collector failures should still produce a valid bundle (exit 0)."""

    def test_versions_failure_still_produces_bundle(self, tmp_path):
        """When versions collector fails, bundle is still created with remaining data."""
        output_path = tmp_path / "test-bundle.tar.gz"
        server_resp = _make_server_response(versions_ok=False)

        with (
            patch("observal_cli.cmd_support.client.post", return_value=server_resp),
        ):
            result = runner.invoke(app, ["doctor", "support", "bundle", "--file", str(output_path)])

        assert result.exit_code == 0, f"Should exit 0 on partial failure: {result.output}"
        assert output_path.exists()

        with tarfile.open(output_path, "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]

        # Manifest should still be present
        assert "bundle_manifest.json" in names
        # versions/ should be absent since that collector failed
        version_files = [n for n in names if n.startswith("versions/")]
        assert len(version_files) == 0

        # But health and config should still be present
        health_files = [n for n in names if n.startswith("health/")]
        assert len(health_files) > 0

    def test_health_failure_still_produces_bundle(self, tmp_path):
        """When health collector fails, bundle is still created."""
        output_path = tmp_path / "test-bundle.tar.gz"
        server_resp = _make_server_response(health_ok=False)

        with (
            patch("observal_cli.cmd_support.client.post", return_value=server_resp),
        ):
            result = runner.invoke(app, ["doctor", "support", "bundle", "--file", str(output_path)])

        assert result.exit_code == 0, f"Should exit 0 on partial failure: {result.output}"
        assert output_path.exists()

    def test_server_unreachable_still_produces_bundle(self, tmp_path):
        """When the server is unreachable, local collectors still run and produce a bundle."""
        output_path = tmp_path / "test-bundle.tar.gz"

        # Simulate server unreachable by raising ConnectError
        with patch("observal_cli.cmd_support.client.post", side_effect=_unavailable()):
            result = runner.invoke(app, ["doctor", "support", "bundle", "--file", str(output_path)])

        assert result.exit_code == 0, f"Should exit 0 with local-only data: {result.output}"
        assert output_path.exists()

        with tarfile.open(output_path, "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]

        # Should still have manifest and system info from local collectors
        assert "bundle_manifest.json" in names
        system_files = [n for n in names if n.startswith("system/")]
        assert len(system_files) > 0, "Local system collector should still run"

    def test_partial_failure_manifest_records_failures(self, tmp_path):
        """Failed collectors should be recorded in the manifest with ok=false."""
        output_path = tmp_path / "test-bundle.tar.gz"
        server_resp = _make_server_response(versions_ok=False, health_ok=False)

        with (
            patch("observal_cli.cmd_support.client.post", return_value=server_resp),
        ):
            result = runner.invoke(app, ["doctor", "support", "bundle", "--file", str(output_path)])

        assert result.exit_code == 0

        with tarfile.open(output_path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember("bundle_manifest.json")).read())

        collector_results = manifest_data["collector_results"]
        assert collector_results["versions"]["ok"] is False
        assert collector_results["health"]["ok"] is False


# ── Total failure ────────────────────────────────────────────────────


class TestTotalFailure:
    """When no data can be collected at all, exit with code 1."""

    def test_all_collectors_fail_exits_1(self, tmp_path):
        """When all collectors fail and no data is available, exit code should be 1."""
        from observal_cli.cmd_support import CollectorResult

        output_path = tmp_path / "test-bundle.tar.gz"

        # All remote collectors fail
        server_resp = _make_server_response(
            versions_ok=False,
            health_ok=False,
            config_ok=False,
        )

        failed_system = CollectorResult(name="system_info", ok=False, duration_ms=0, data=None, error="fail")
        failed_config = CollectorResult(name="config_allowlisted", ok=False, duration_ms=0, data=None, error="fail")

        # Mock both local collectors to fail, and disable system import
        with (
            patch("observal_cli.cmd_support.client.post", return_value=server_resp),
            patch("observal_cli.cmd_support._config_allowlisted", return_value=failed_config),
            patch(
                "observal_cli.support.collectors.system_info",
                return_value=failed_system,
            ),
        ):
            result = runner.invoke(app, ["doctor", "support", "bundle", "--file", str(output_path)])

        assert result.exit_code == 9, f"Should exit 9 when no data is available: {result.output}"
        assert not output_path.exists(), "No archive should be written on total failure"

    def test_empty_server_response_with_failed_local_exits_1(self, tmp_path):
        """Empty server response + failed local collectors = exit 1."""
        from observal_cli.cmd_support import CollectorResult

        output_path = tmp_path / "test-bundle.tar.gz"

        failed_config = CollectorResult(name="config_allowlisted", ok=False, duration_ms=0, data=None, error="fail")

        with (
            patch("observal_cli.cmd_support.client.post", side_effect=_unavailable()),
            patch("observal_cli.cmd_support._config_allowlisted", return_value=failed_config),
        ):
            result = runner.invoke(
                app,
                ["doctor", "support", "bundle", "--file", str(output_path), "--no-include-system"],
            )

        assert result.exit_code == 9, f"Should exit 9 when no data is available: {result.output}"


def test_bundle_json_returns_archive_metadata_without_human_output(tmp_path):
    output_path = tmp_path / "bundle.tar.gz"
    server_response = _make_server_response()

    with patch("observal_cli.cmd_support.client.post", return_value=server_response):
        result = runner.invoke(
            app,
            ["doctor", "support", "bundle", "--file", str(output_path), "--output", "json"],
        )

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["path"] == str(output_path)
    assert data["size_bytes"] == output_path.stat().st_size
    assert data["remote_status"] == "collected"
    assert data["warnings"] == []
    assert "Support bundle written" not in result.stdout


def test_bundle_json_reports_explicit_local_fallback(tmp_path):
    output_path = tmp_path / "local-bundle.tar.gz"

    with patch("observal_cli.cmd_support.client.post", side_effect=_unavailable()):
        result = runner.invoke(
            app,
            ["doctor", "support", "bundle", "--file", str(output_path), "--output", "json"],
        )

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["remote_status"] == "unavailable"
    assert data["warnings"]
    assert output_path.is_file()


def test_bundle_json_validation_uses_shared_error_contract(tmp_path):
    existing = tmp_path / "existing.tar.gz"
    existing.write_bytes(b"keep")

    invalid_duration = runner.invoke(
        app,
        ["doctor", "support", "bundle", "--logs-since", "forever", "--output", "json"],
    )
    existing_file = runner.invoke(
        app,
        ["doctor", "support", "bundle", "--file", str(existing), "--output", "json"],
    )

    assert invalid_duration.exit_code == 7
    assert invalid_duration.stdout == ""
    assert json.loads(invalid_duration.stderr)["error"]["category"] == "validation"
    assert existing_file.exit_code == 6
    assert existing_file.stdout == ""
    assert json.loads(existing_file.stderr)["error"]["category"] == "conflict"
    assert existing.read_bytes() == b"keep"
