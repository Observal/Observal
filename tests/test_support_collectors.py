# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for observal_cli/support/collectors.py — local system collector.

Covers:
- system_info collector returns correct structure
- No hostnames, IP addresses, or usernames in output
- OS/kernel/CPU fields populated from platform/os modules
- Memory fields populated via os.sysconf (POSIX)
- Disk usage fields populated via shutil.disk_usage
- Container runtime detection (Docker, Podman, none)
- Graceful error handling (ok=False on exception)
- Only runs when --include-system flag is active
"""

from __future__ import annotations

from unittest.mock import patch

from observal_cli.cmd_support import CollectorResult
from observal_cli.support.collectors import (
    _detect_container_runtime,
    _get_memory_available,
    _get_memory_total,
    system_info,
)

# ── system_info collector ────────────────────────────────────────────


class TestSystemInfo:
    def test_returns_collector_result(self):
        result = system_info({}, {})
        assert isinstance(result, CollectorResult)

    def test_result_name(self):
        result = system_info({}, {})
        assert result.name == "system_info"

    def test_result_ok_on_success(self):
        result = system_info({}, {})
        assert result.ok is True

    def test_result_has_duration(self):
        result = system_info({}, {})
        assert isinstance(result.duration_ms, int)
        assert result.duration_ms >= 0

    def test_result_error_is_none_on_success(self):
        result = system_info({}, {})
        assert result.error is None

    def test_data_contains_required_keys(self):
        result = system_info({}, {})
        assert result.ok is True
        data = result.data
        required_keys = {
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
        assert required_keys == set(data.keys())

    def test_os_name_is_string(self):
        result = system_info({}, {})
        assert isinstance(result.data["os_name"], str)
        assert len(result.data["os_name"]) > 0

    def test_os_version_is_string(self):
        result = system_info({}, {})
        assert isinstance(result.data["os_version"], str)

    def test_kernel_version_is_string(self):
        result = system_info({}, {})
        assert isinstance(result.data["kernel_version"], str)

    def test_cpu_count_is_positive_int(self):
        result = system_info({}, {})
        cpu = result.data["cpu_count"]
        assert isinstance(cpu, int)
        assert cpu > 0

    def test_disk_total_is_positive(self):
        result = system_info({}, {})
        assert result.data["disk_total_bytes"] is None or result.data["disk_total_bytes"] > 0

    def test_disk_free_is_non_negative(self):
        result = system_info({}, {})
        assert result.data["disk_free_bytes"] is None or result.data["disk_free_bytes"] >= 0

    def test_container_runtime_is_string_or_none(self):
        result = system_info({}, {})
        rt = result.data["container_runtime"]
        assert rt is None or isinstance(rt, str)

    def test_target_path(self):
        result = system_info({}, {})
        assert result.target_path == "system/system.json"


# ── No PII in output ────────────────────────────────────────────────


class TestNoPII:
    """Verify no hostnames, IP addresses, or usernames leak into system_info."""

    def test_no_hostname_in_data(self):
        import socket

        hostname = socket.gethostname()
        result = system_info({}, {})
        data_str = str(result.data)
        # Only check if hostname is non-trivial (not a common word)
        if len(hostname) > 3 and hostname not in ("Linux", "Darwin", "Windows"):
            assert hostname not in data_str

    def test_no_username_in_data(self):
        import os

        try:
            username = os.getlogin()
        except OSError:
            username = os.environ.get("USER", os.environ.get("USERNAME", ""))
        result = system_info({}, {})
        data_str = str(result.data)
        # Only check if username is non-trivial
        if len(username) > 3 and username not in ("root", "Linux", "Darwin", "Windows"):
            assert username not in data_str

    def test_data_keys_contain_no_hostname_field(self):
        result = system_info({}, {})
        for key in result.data:
            assert "hostname" not in key.lower()
            assert "ip_address" not in key.lower()
            assert "username" not in key.lower()


# ── Memory helpers ───────────────────────────────────────────────────


class TestMemoryHelpers:
    def test_memory_total_returns_int_or_none(self):
        val = _get_memory_total()
        assert val is None or (isinstance(val, int) and val > 0)

    def test_memory_available_returns_int_or_none(self):
        val = _get_memory_available()
        assert val is None or (isinstance(val, int) and val > 0)

    def test_memory_total_fallback_on_non_posix(self):
        with patch("observal_cli.support.collectors.os.sysconf", create=True, side_effect=AttributeError):
            val = _get_memory_total()
            assert val is None

    def test_memory_available_fallback_on_non_posix(self):
        with patch("observal_cli.support.collectors.os.sysconf", create=True, side_effect=AttributeError):
            val = _get_memory_available()
            assert val is None

    def test_memory_total_fallback_on_os_error(self):
        with patch("observal_cli.support.collectors.os.sysconf", create=True, side_effect=OSError):
            val = _get_memory_total()
            assert val is None

    def test_memory_available_fallback_on_value_error(self):
        with patch("observal_cli.support.collectors.os.sysconf", create=True, side_effect=ValueError):
            val = _get_memory_available()
            assert val is None


# ── Container runtime detection ──────────────────────────────────────


class TestContainerRuntimeDetection:
    def test_detects_docker(self):
        with patch("observal_cli.support.collectors.os.path.exists") as mock_exists:
            mock_exists.side_effect = lambda p: p == "/.dockerenv"
            assert _detect_container_runtime() == "docker"

    def test_detects_podman(self):
        with patch("observal_cli.support.collectors.os.path.exists") as mock_exists:
            mock_exists.side_effect = lambda p: p == "/run/.containerenv"
            assert _detect_container_runtime() == "podman"

    def test_returns_none_when_no_container(self):
        with patch("observal_cli.support.collectors.os.path.exists", return_value=False):
            assert _detect_container_runtime() is None

    def test_docker_takes_precedence_over_podman(self):
        """If both markers exist, Docker is detected first."""
        with patch("observal_cli.support.collectors.os.path.exists", return_value=True):
            assert _detect_container_runtime() == "docker"


# ── Error handling ───────────────────────────────────────────────────


class TestErrorHandling:
    def test_returns_ok_false_on_exception(self):
        with patch("observal_cli.support.collectors.platform.system", side_effect=RuntimeError("boom")):
            result = system_info({}, {})
            assert result.ok is False
            assert result.error == "boom"
            assert result.data is None
            assert result.name == "system_info"

    def test_disk_usage_failure_sets_none(self):
        with patch("observal_cli.support.collectors.shutil.disk_usage", side_effect=OSError("no disk")):
            result = system_info({}, {})
            assert result.ok is True
            assert result.data["disk_total_bytes"] is None
            assert result.data["disk_free_bytes"] is None
