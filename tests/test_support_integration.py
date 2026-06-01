# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""End-to-end integration test for the support bundle feature.

Mocks the API server's /api/v1/support/collect endpoint, runs
`observal support bundle` via Typer's CliRunner, and verifies:
- The archive is a valid .tar.gz
- Directory structure matches spec: bundle_manifest.json, versions/,
  config/, health/, aggregates/, errors/, logs/, system/
- File permissions are 0o600
- Manifest contains all required fields
- File inventory SHA-256 hashes are correct

Validates: Requirements 1.1, 1.2, 2.1, 2.2, 4.1, 4.5, 7.1, 7.3
"""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
from unittest.mock import MagicMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from observal_cli.main import app

runner = CliRunner()


# ── Realistic mock server response ───────────────────────────────────


def _full_server_response() -> dict:
    """Build a realistic /api/v1/support/collect response with all collectors."""
    return {
        "server_version": "0.9.5",
        "collectors": {
            "versions": {
                "ok": True,
                "duration_ms": 45,
                "data": {
                    "app_version": "0.9.5",
                    "build_hash": "abc123def456",
                    "alembic_revision": "a1b2c3d4e5f6",
                    "clickhouse_version": "24.3.1.2672",
                    "clickhouse_tables": ["traces", "spans", "scores"],
                },
            },
            "health": {
                "ok": True,
                "duration_ms": 28,
                "data": {
                    "postgres": {"status": "ok", "latency_ms": 3},
                    "clickhouse": {"status": "ok", "latency_ms": 7},
                    "redis": {"status": "ok", "latency_ms": 1},
                    "otel_collector": {"status": "ok", "latency_ms": 12},
                },
            },
            "config": {
                "ok": True,
                "duration_ms": 5,
                "data": {
                    "DATABASE_URL": "postgresql+asyncpg://admin:s3cret@localhost:5432/observal",
                    "CLICKHOUSE_URL": "clickhouse://default:pass@localhost:8123/observal",
                    "REDIS_URL": "redis://localhost:6379",
                    "REDIS_SOCKET_TIMEOUT": 5,
                    "EVAL_MODEL_NAME": "gpt-4",
                    "EVAL_MODEL_PROVIDER": "openai",
                    "AWS_REGION": "us-east-1",
                    "FRONTEND_URL": "http://localhost:3000",
                    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": 30,
                    "JWT_REFRESH_TOKEN_EXPIRE_DAYS": 7,
                    "JWT_SIGNING_ALGORITHM": "RS256",
                    "JWT_HOOKS_TOKEN_EXPIRE_MINUTES": 60,
                    "RATE_LIMIT_AUTH": "10/minute",
                    "RATE_LIMIT_AUTH_STRICT": "3/minute",
                    "DATA_RETENTION_DAYS": 90,
                    "DEPLOYMENT_MODE": "docker",
                    # These should be filtered out by the allowlist
                    "SECRET_KEY": "super-secret-key-value",
                    "OAUTH_CLIENT_SECRET": "oauth-secret-123",
                },
            },
            "aggregates": {
                "ok": True,
                "duration_ms": 120,
                "data": {
                    "pg_table_counts": {
                        "users": 42,
                        "agents": 15,
                        "mcp_listings": 8,
                        "feedback": 200,
                    },
                    "ch_table_counts": {
                        "traces": 1000000,
                        "spans": 5000000,
                        "scores": 50000,
                    },
                },
            },
            "errors": {
                "ok": True,
                "duration_ms": 80,
                "data": {
                    "fingerprints": [
                        {
                            "fingerprint": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
                            "count": 12,
                            "first_seen": "2025-07-14T10:00:00Z",
                            "last_seen": "2025-07-15T08:30:00Z",
                            "stack_template": "api/routes/telemetry.py:ingest -> services/clickhouse.py:insert_batch",
                        }
                    ]
                },
            },
            "logs": {
                "ok": True,
                "duration_ms": 15,
                "data": {
                    "lines": [
                        {
                            "timestamp": "2025-07-15T09:00:00Z",
                            "level": "info",
                            "event": "Request processed",
                            "path": "/api/v1/traces",
                            "status": 200,
                        },
                        {
                            "timestamp": "2025-07-15T09:01:00Z",
                            "level": "warning",
                            "event": "Slow query detected",
                            "duration_ms": 1500,
                        },
                    ]
                },
            },
        },
    }


def _mock_httpx_response(data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


# ── Required directories in the archive ──────────────────────────────

REQUIRED_PREFIXES = [
    "versions/",
    "config/",
    "health/",
    "aggregates/",
    "errors/",
    "logs/",
    "system/",
]


# ── Required manifest fields ─────────────────────────────────────────

REQUIRED_MANIFEST_FIELDS = [
    "bundle_schema_version",
    "created_at",
    "cli_version",
    "host_os",
    "flags_used",
    "collector_results",
    "redaction_counts",
    "file_inventory",
]


# ── Integration test ─────────────────────────────────────────────────


class TestSupportBundleIntegration:
    """Full end-to-end integration test for `observal support bundle`."""

    @pytest.fixture()
    def bundle_path(self, tmp_path):
        """Generate a bundle archive and return its path."""
        output = tmp_path / "integration-test-bundle.tar.gz"
        server_resp = _full_server_response()
        mock_cfg = {"server_url": "http://localhost:8000", "access_token": "test-token"}

        with (
            patch("observal_cli.cmd_support.config.get_or_exit", return_value=mock_cfg),
            patch("observal_cli.cmd_support.config.get_timeout", return_value=30),
            patch(
                "observal_cli.cmd_support.httpx.post",
                return_value=_mock_httpx_response(server_resp),
            ),
        ):
            result = runner.invoke(app, ["doctor", "support", "bundle", "--output", str(output)])

        assert result.exit_code == 0, f"Bundle command failed: {result.output}"
        assert output.exists(), "Archive file was not created"
        return output

    # ── 1. Archive is valid tar.gz ───────────────────────

    def test_archive_is_valid_tar_gz(self, bundle_path):
        """The produced file must be a valid gzip-compressed tar archive."""
        assert tarfile.is_tarfile(bundle_path)
        with tarfile.open(bundle_path, "r:gz") as tar:
            members = tar.getmembers()
            assert len(members) > 0, "Archive should not be empty"

    # ── 2. Directory structure matches spec ──────────────

    def test_bundle_manifest_present(self, bundle_path):
        """bundle_manifest.json must be at the root of the archive."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            names = tar.getnames()
            assert "bundle_manifest.json" in names

    def test_all_required_directories_present(self, bundle_path):
        """Archive must contain files under each required directory prefix."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            names = tar.getnames()

        for prefix in REQUIRED_PREFIXES:
            matching = [n for n in names if n.startswith(prefix)]
            assert len(matching) > 0, (
                f"Expected files under '{prefix}' but found none. Archive contents: {sorted(names)}"
            )

    def test_versions_directory_files(self, bundle_path):
        """versions/ should contain app.json, alembic.json, clickhouse.json."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            names = tar.getnames()

        assert "versions/app.json" in names
        assert "versions/alembic.json" in names
        assert "versions/clickhouse.json" in names

    def test_health_directory_files(self, bundle_path):
        """health/ should contain per-service JSON files."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            names = tar.getnames()

        health_files = [n for n in names if n.startswith("health/")]
        assert "health/postgres.json" in names
        assert "health/clickhouse.json" in names
        assert "health/redis.json" in names
        assert "health/otel_collector.json" in names

    def test_aggregates_directory_files(self, bundle_path):
        """aggregates/ should contain pg_table_counts.json and ch_table_counts.json."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            names = tar.getnames()

        assert "aggregates/pg_table_counts.json" in names
        assert "aggregates/ch_table_counts.json" in names

    def test_errors_directory_files(self, bundle_path):
        """errors/ should contain recent_errors.json."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            names = tar.getnames()

        assert "errors/recent_errors.json" in names

    def test_logs_directory_files(self, bundle_path):
        """logs/ should contain recent.ndjson."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            names = tar.getnames()

        assert "logs/recent.ndjson" in names

    def test_system_directory_files(self, bundle_path):
        """system/ should contain system.json (default --include-system)."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            names = tar.getnames()

        assert "system/system.json" in names

    def test_config_directory_files(self, bundle_path):
        """config/ should contain config.json."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            names = tar.getnames()

        assert "config/config.json" in names

    # ── 3. File permissions are 0o600 ────────────────────

    def test_archive_permissions_0o600(self, bundle_path):
        """The archive file must have 0o600 permissions (owner read/write only)."""
        if os.name == "nt":
            pytest.skip("File permission check not applicable on Windows")

        mode = os.stat(bundle_path).st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    # ── 4. Manifest contains all required fields ─────────

    def test_manifest_has_all_required_fields(self, bundle_path):
        """bundle_manifest.json must contain all fields from the spec."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember("bundle_manifest.json")).read())

        for field_name in REQUIRED_MANIFEST_FIELDS:
            assert field_name in manifest_data, (
                f"Manifest missing required field: '{field_name}'. Present fields: {list(manifest_data.keys())}"
            )

    def test_manifest_schema_version_is_1(self, bundle_path):
        """bundle_schema_version must be '1'."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember("bundle_manifest.json")).read())

        assert manifest_data["bundle_schema_version"] == "1"

    def test_manifest_created_at_is_iso8601(self, bundle_path):
        """created_at must be a valid ISO 8601 timestamp."""
        from datetime import datetime

        with tarfile.open(bundle_path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember("bundle_manifest.json")).read())

        created_at = manifest_data["created_at"]
        # Should parse without error
        dt = datetime.fromisoformat(created_at)
        assert dt is not None

    def test_manifest_cli_version_present(self, bundle_path):
        """cli_version must be a non-empty string."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember("bundle_manifest.json")).read())

        assert isinstance(manifest_data["cli_version"], str)
        assert len(manifest_data["cli_version"]) > 0

    def test_manifest_host_os_present(self, bundle_path):
        """host_os must be a non-empty string."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember("bundle_manifest.json")).read())

        assert isinstance(manifest_data["host_os"], str)
        assert len(manifest_data["host_os"]) > 0

    def test_manifest_flags_used_records_options(self, bundle_path):
        """flags_used must record the flags passed to the bundle command."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember("bundle_manifest.json")).read())

        flags = manifest_data["flags_used"]
        assert isinstance(flags, dict)
        assert "output" in flags
        assert "logs_since" in flags
        assert "include_system" in flags

    def test_manifest_collector_results_present(self, bundle_path):
        """collector_results must map collector names to ok/duration_ms."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember("bundle_manifest.json")).read())

        results = manifest_data["collector_results"]
        assert isinstance(results, dict)
        assert len(results) > 0
        # Each entry should have 'ok' and 'duration_ms'
        for name, entry in results.items():
            assert "ok" in entry, f"Collector '{name}' missing 'ok' field"
            assert "duration_ms" in entry, f"Collector '{name}' missing 'duration_ms' field"

    def test_manifest_file_inventory_present(self, bundle_path):
        """file_inventory must be a non-empty list of file entries."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember("bundle_manifest.json")).read())

        inventory = manifest_data["file_inventory"]
        assert isinstance(inventory, list)
        assert len(inventory) > 0

        # Each entry must have path, size_bytes, sha256
        for entry in inventory:
            assert "path" in entry, f"Inventory entry missing 'path': {entry}"
            assert "size_bytes" in entry, f"Inventory entry missing 'size_bytes': {entry}"
            assert "sha256" in entry, f"Inventory entry missing 'sha256': {entry}"

    # ── 5. File inventory SHA-256 hashes are correct ─────

    def test_file_inventory_sha256_integrity(self, bundle_path):
        """Every SHA-256 hash in file_inventory must match the actual file content."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember("bundle_manifest.json")).read())

            inventory = manifest_data["file_inventory"]
            assert len(inventory) > 0, "File inventory should not be empty"

            for entry in inventory:
                rel_path = entry["path"]
                expected_sha = entry["sha256"]
                expected_size = entry["size_bytes"]

                # Read the actual file content from the archive
                member = tar.getmember(rel_path)
                content = tar.extractfile(member).read()

                # Verify SHA-256
                actual_sha = hashlib.sha256(content).hexdigest()
                assert actual_sha == expected_sha, (
                    f"SHA-256 mismatch for '{rel_path}': manifest={expected_sha}, actual={actual_sha}"
                )

                # Verify size
                assert len(content) == expected_size, (
                    f"Size mismatch for '{rel_path}': manifest={expected_size}, actual={len(content)}"
                )

    # ── 6. Content correctness spot checks ───────────────

    def test_versions_app_json_content(self, bundle_path):
        """versions/app.json should contain cli_version and server_version."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            data = json.loads(tar.extractfile(tar.getmember("versions/app.json")).read())

        assert "cli_version" in data
        assert "server_version" in data
        assert data["server_version"] == "0.9.5"

    def test_versions_alembic_json_content(self, bundle_path):
        """versions/alembic.json should contain current_revision."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            data = json.loads(tar.extractfile(tar.getmember("versions/alembic.json")).read())

        assert "current_revision" in data
        assert data["current_revision"] == "a1b2c3d4e5f6"

    def test_versions_clickhouse_json_content(self, bundle_path):
        """versions/clickhouse.json should contain server_version and tables."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            data = json.loads(tar.extractfile(tar.getmember("versions/clickhouse.json")).read())

        assert "server_version" in data
        assert "tables" in data
        assert data["server_version"] == "24.3.1.2672"
        assert isinstance(data["tables"], list)

    def test_config_excludes_secrets(self, bundle_path):
        """config/config.json must not contain SECRET_KEY or OAUTH_CLIENT_SECRET."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            data = json.loads(tar.extractfile(tar.getmember("config/config.json")).read())

        assert "SECRET_KEY" not in data
        assert "OAUTH_CLIENT_SECRET" not in data

    def test_config_redacts_url_credentials(self, bundle_path):
        """DATABASE_URL in config should have credentials redacted."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            data = json.loads(tar.extractfile(tar.getmember("config/config.json")).read())

        if "DATABASE_URL" in data:
            assert "s3cret" not in data["DATABASE_URL"]
            assert "<REDACTED>" in data["DATABASE_URL"]

    def test_aggregates_contain_counts(self, bundle_path):
        """Aggregate files should contain table count data."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            pg_data = json.loads(tar.extractfile(tar.getmember("aggregates/pg_table_counts.json")).read())
            ch_data = json.loads(tar.extractfile(tar.getmember("aggregates/ch_table_counts.json")).read())

        assert isinstance(pg_data, dict)
        assert isinstance(ch_data, dict)
        assert pg_data.get("users") == 42
        assert ch_data.get("traces") == 1000000

    def test_errors_contain_fingerprints(self, bundle_path):
        """errors/recent_errors.json should contain fingerprint data."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            data = json.loads(tar.extractfile(tar.getmember("errors/recent_errors.json")).read())

        assert "fingerprints" in data
        assert len(data["fingerprints"]) == 1
        fp = data["fingerprints"][0]
        assert "fingerprint" in fp
        assert "count" in fp
        assert "stack_template" in fp

    def test_system_json_has_required_keys(self, bundle_path):
        """system/system.json should contain OS, CPU, memory, disk info."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            data = json.loads(tar.extractfile(tar.getmember("system/system.json")).read())

        expected_keys = {
            "os_name",
            "os_version",
            "kernel_version",
            "cpu_count",
            "memory_total_bytes",
            "memory_available_bytes",
            "disk_total_bytes",
            "disk_free_bytes",
            "container_runtime",
        }
        assert expected_keys == set(data.keys())

    # ── 7. Manifest is valid JSON (round-trip) ───────────

    def test_manifest_is_valid_json(self, bundle_path):
        """The manifest must be valid JSON that can be parsed and re-serialized."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            raw = tar.extractfile(tar.getmember("bundle_manifest.json")).read()

        # Parse
        data = json.loads(raw)
        # Re-serialize
        reserialized = json.dumps(data, indent=2)
        # Re-parse
        data2 = json.loads(reserialized)
        assert data == data2

    # ── 8. All archive files are valid JSON or text ──────

    def test_all_json_files_are_valid(self, bundle_path):
        """Every .json file in the archive must be valid JSON."""
        with tarfile.open(bundle_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile() and member.name.endswith(".json"):
                    content = tar.extractfile(member).read()
                    try:
                        json.loads(content)
                    except json.JSONDecodeError:
                        pytest.fail(f"File '{member.name}' is not valid JSON: {content[:200]!r}")


# ── No --include-system variant ──────────────────────────────────────


class TestBundleWithoutSystem:
    """Verify --no-include-system excludes the system/ directory."""

    def test_no_system_directory(self, tmp_path):
        output = tmp_path / "no-system-bundle.tar.gz"
        server_resp = _full_server_response()
        mock_cfg = {"server_url": "http://localhost:8000", "access_token": "test-token"}

        with (
            patch("observal_cli.cmd_support.config.get_or_exit", return_value=mock_cfg),
            patch("observal_cli.cmd_support.config.get_timeout", return_value=30),
            patch(
                "observal_cli.cmd_support.httpx.post",
                return_value=_mock_httpx_response(server_resp),
            ),
        ):
            result = runner.invoke(
                app,
                ["doctor", "support", "bundle", "--output", str(output), "--no-include-system"],
            )

        assert result.exit_code == 0
        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()

        system_files = [n for n in names if n.startswith("system/")]
        assert len(system_files) == 0, "system/ should be absent with --no-include-system"

        # All other required directories should still be present
        for prefix in ["versions/", "config/", "health/", "aggregates/", "errors/", "logs/"]:
            matching = [n for n in names if n.startswith(prefix)]
            assert len(matching) > 0, f"Expected files under '{prefix}'"
