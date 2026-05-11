# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for observal_cli/cmd_support.py — bundle command module.

Covers:
- CONFIG_ALLOWLIST contents and count
- CollectorResult dataclass and target_path mapping
- _config_allowlisted local collector
- _add_bytes_to_tar helper
- _write_archive with atomic rename and 0o600 permissions
- _human_size formatting
- bundle command orchestration (mocked server)
- Size budget warning threshold
"""

from __future__ import annotations

import io
import json
import os
import tarfile
from unittest.mock import patch

import pytest

from observal_cli.cmd_support import (
    CONFIG_ALLOWLIST,
    SIZE_BUDGET_BYTES,
    CollectorResult,
    _add_bytes_to_tar,
    _config_allowlisted,
    _human_size,
    _write_archive,
    support_app,
)
from observal_cli.support.manifest import BundleManifest

# ── CONFIG_ALLOWLIST ─────────────────────────────────────────────────


class TestConfigAllowlist:
    def test_allowlist_is_frozenset(self):
        assert isinstance(CONFIG_ALLOWLIST, frozenset)

    def test_allowlist_has_16_keys(self):
        assert len(CONFIG_ALLOWLIST) == 16

    def test_allowlist_contains_expected_keys(self):
        expected = {
            "DATABASE_URL",
            "CLICKHOUSE_URL",
            "REDIS_URL",
            "REDIS_SOCKET_TIMEOUT",
            "EVAL_MODEL_NAME",
            "EVAL_MODEL_PROVIDER",
            "AWS_REGION",
            "FRONTEND_URL",
            "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
            "JWT_REFRESH_TOKEN_EXPIRE_DAYS",
            "JWT_SIGNING_ALGORITHM",
            "JWT_HOOKS_TOKEN_EXPIRE_MINUTES",
            "RATE_LIMIT_AUTH",
            "RATE_LIMIT_AUTH_STRICT",
            "DATA_RETENTION_DAYS",
            "DEPLOYMENT_MODE",
        }
        assert expected == CONFIG_ALLOWLIST

    def test_allowlist_excludes_secrets(self):
        """Keys that must never appear in the allowlist."""
        forbidden = {
            "SECRET_KEY",
            "EVAL_MODEL_API_KEY",
            "EVAL_MODEL_URL",
            "OAUTH_CLIENT_ID",
            "OAUTH_CLIENT_SECRET",
            "OAUTH_SERVER_METADATA_URL",
            "JWT_KEY_DIR",
            "JWT_KEY_PASSWORD",
        }
        assert CONFIG_ALLOWLIST.isdisjoint(forbidden)


# ── CollectorResult ──────────────────────────────────────────────────


class TestCollectorResult:
    def test_basic_creation(self):
        r = CollectorResult(name="versions", ok=True, duration_ms=42, data={"v": "1"})
        assert r.name == "versions"
        assert r.ok is True
        assert r.duration_ms == 42
        assert r.data == {"v": "1"}
        assert r.error is None

    def test_error_field(self):
        r = CollectorResult(name="health", ok=False, duration_ms=100, data=None, error="timeout")
        assert r.error == "timeout"

    def test_target_path_versions(self):
        r = CollectorResult(name="versions", ok=True, duration_ms=0, data={})
        assert r.target_path == "versions/app.json"

    def test_target_path_health(self):
        r = CollectorResult(name="health", ok=True, duration_ms=0, data={})
        assert r.target_path == "health/health.json"

    def test_target_path_config_allowlisted(self):
        r = CollectorResult(name="config_allowlisted", ok=True, duration_ms=0, data={})
        assert r.target_path == "config/config.json"

    def test_target_path_system_info(self):
        r = CollectorResult(name="system_info", ok=True, duration_ms=0, data={})
        assert r.target_path == "system/system.json"

    def test_target_path_unknown_collector(self):
        r = CollectorResult(name="custom_thing", ok=True, duration_ms=0, data={})
        assert r.target_path == "custom_thing.json"


# ── _config_allowlisted ─────────────────────────────────────────────


class TestConfigAllowlistedCollector:
    def test_filters_to_allowlist(self):
        server_response = {
            "collectors": {
                "config": {
                    "ok": True,
                    "duration_ms": 5,
                    "data": {
                        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/db",
                        "SECRET_KEY": "super-secret-value",
                        "AWS_REGION": "us-east-1",
                        "DEPLOYMENT_MODE": "docker",
                    },
                }
            }
        }
        result = _config_allowlisted(server_response)
        assert result.ok is True
        assert result.name == "config_allowlisted"
        assert isinstance(result.data, dict)
        # SECRET_KEY must be filtered out
        assert "SECRET_KEY" not in result.data
        # Allowlisted keys should be present
        assert "AWS_REGION" in result.data
        assert "DEPLOYMENT_MODE" in result.data
        # DATABASE_URL should be present but redacted (URL userinfo)
        assert "DATABASE_URL" in result.data

    def test_redacts_url_userinfo(self):
        server_response = {
            "collectors": {
                "config": {
                    "ok": True,
                    "duration_ms": 5,
                    "data": {
                        "DATABASE_URL": "postgresql+asyncpg://admin:s3cret@localhost:5432/observal",
                    },
                }
            }
        }
        result = _config_allowlisted(server_response)
        assert result.ok is True
        db_url = result.data["DATABASE_URL"]
        # The credential portion must be redacted
        assert "s3cret" not in db_url
        assert "<REDACTED>" in db_url

    def test_handles_empty_server_response(self):
        result = _config_allowlisted({})
        assert result.ok is True
        assert result.data == {}

    def test_handles_missing_config_collector(self):
        result = _config_allowlisted({"collectors": {}})
        assert result.ok is True
        assert result.data == {}

    def test_handles_non_dict_config_data(self):
        server_response = {
            "collectors": {
                "config": {
                    "ok": True,
                    "duration_ms": 5,
                    "data": "not a dict",
                }
            }
        }
        result = _config_allowlisted(server_response)
        assert result.ok is True
        assert result.data == {}


# ── _add_bytes_to_tar ────────────────────────────────────────────────


class TestAddBytesToTar:
    def test_adds_file_to_tar(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            _add_bytes_to_tar(tar, "test/file.json", b'{"key": "value"}')

        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            member = tar.getmember("test/file.json")
            assert member.size == len(b'{"key": "value"}')
            content = tar.extractfile(member).read()
            assert json.loads(content) == {"key": "value"}

    def test_adds_empty_file(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            _add_bytes_to_tar(tar, "empty.txt", b"")

        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            member = tar.getmember("empty.txt")
            assert member.size == 0


# ── _write_archive ───────────────────────────────────────────────────


class TestWriteArchive:
    def test_creates_valid_tar_gz(self, tmp_path):
        output = tmp_path / "test.tar.gz"
        files = {
            "config/config.json": b'{"key": "value"}',
            "versions/app.json": b'{"version": "1.0"}',
        }
        manifest = BundleManifest(
            bundle_schema_version="1",
            created_at="2025-01-01T00:00:00+00:00",
            cli_version="1.0.0",
        )

        _write_archive(output, files, manifest)

        assert output.exists()
        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()
            assert "bundle_manifest.json" in names
            assert "config/config.json" in names
            assert "versions/app.json" in names

    def test_sets_0o600_permissions(self, tmp_path):
        output = tmp_path / "test.tar.gz"
        files = {"test.json": b"{}"}
        manifest = BundleManifest()

        _write_archive(output, files, manifest)

        # On POSIX, check permissions
        if os.name != "nt":
            mode = oct(os.stat(output).st_mode & 0o777)
            assert mode == "0o600"

    def test_manifest_is_first_entry(self, tmp_path):
        output = tmp_path / "test.tar.gz"
        files = {"a.json": b"{}", "z.json": b"{}"}
        manifest = BundleManifest()

        _write_archive(output, files, manifest)

        with tarfile.open(output, "r:gz") as tar:
            members = tar.getnames()
            assert members[0] == "bundle_manifest.json"

    def test_atomic_write_cleans_up_on_failure(self, tmp_path):
        output = tmp_path / "test.tar.gz"

        # Create a manifest that will cause serialization to fail
        manifest = BundleManifest()

        # Patch tarfile.open to raise after creating temp file
        with (
            patch("observal_cli.cmd_support.tarfile.open", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            _write_archive(output, {"test.json": b"{}"}, manifest)

        # Output should not exist
        assert not output.exists()

    def test_creates_parent_directories(self, tmp_path):
        output = tmp_path / "nested" / "dir" / "test.tar.gz"
        files = {"test.json": b"{}"}
        manifest = BundleManifest()

        _write_archive(output, files, manifest)
        assert output.exists()


# ── _human_size ──────────────────────────────────────────────────────


class TestHumanSize:
    def test_bytes(self):
        assert _human_size(42) == "42 B"

    def test_kilobytes(self):
        result = _human_size(2048)
        assert "KB" in result

    def test_megabytes(self):
        result = _human_size(5 * 1024 * 1024)
        assert "MB" in result

    def test_zero(self):
        assert _human_size(0) == "0 B"


# ── Size budget ──────────────────────────────────────────────────────


class TestSizeBudget:
    def test_budget_is_100mb(self):
        assert SIZE_BUDGET_BYTES == 100 * 1024 * 1024


# ── support_app registration ─────────────────────────────────────────


class TestSupportApp:
    def test_support_app_has_help_text(self):
        assert "no customer data" in support_app.info.help.lower()

    def test_bundle_command_registered(self):
        # Check that 'bundle' is a registered command
        command_names = []
        for cmd_info in support_app.registered_commands:
            if hasattr(cmd_info, "name") and cmd_info.name:
                command_names.append(cmd_info.name)
            elif hasattr(cmd_info, "callback") and cmd_info.callback:
                command_names.append(cmd_info.callback.__name__)
        assert "bundle" in command_names

    def test_bundle_docstring_mentions_no_customer_data(self):
        from observal_cli.cmd_support import bundle

        assert bundle.__doc__ is not None
        first_line = bundle.__doc__.strip().split("\n")[0]
        assert "no customer data" in first_line.lower()
