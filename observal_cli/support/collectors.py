# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Local diagnostic collectors for the support bundle.

Each collector returns a CollectorResult with structured data.
Collectors do NOT perform their own redaction — all output passes
through the central Redaction Layer in cmd_support.py.
"""

from __future__ import annotations

import os
import platform
import shutil
import time

from observal_cli.cmd_support import CollectorResult


def system_info(flags: dict, server_response: dict) -> CollectorResult:
    """Collect local system metrics: OS, kernel, CPU, memory, disk, container runtime.

    Returns a CollectorResult with name="system_info".
    No hostnames, IP addresses, or usernames are included.
    Only runs when --include-system flag is active (default).
    """
    t0 = time.monotonic()
    try:
        data: dict = {}

        # OS name and version
        data["os_name"] = platform.system()
        data["os_version"] = platform.version()

        # Kernel version
        data["kernel_version"] = platform.release()

        # CPU count
        data["cpu_count"] = os.cpu_count()

        # Memory: use os.sysconf on POSIX, fallback to None
        data["memory_total_bytes"] = _get_memory_total()
        data["memory_available_bytes"] = _get_memory_available()

        # Disk usage (root partition)
        try:
            usage = shutil.disk_usage("/")
            data["disk_total_bytes"] = usage.total
            data["disk_free_bytes"] = usage.free
        except OSError:
            data["disk_total_bytes"] = None
            data["disk_free_bytes"] = None

        # Container runtime detection
        data["container_runtime"] = _detect_container_runtime()

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return CollectorResult(
            name="system_info",
            ok=True,
            duration_ms=elapsed_ms,
            data=data,
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return CollectorResult(
            name="system_info",
            ok=False,
            duration_ms=elapsed_ms,
            data=None,
            error=str(exc),
        )


def _get_memory_total() -> int | None:
    """Get total physical memory in bytes using os.sysconf (POSIX only)."""
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return pages * page_size
    except (ValueError, OSError, AttributeError):
        pass
    return None


def _get_memory_available() -> int | None:
    """Get available memory in bytes using os.sysconf (POSIX only)."""
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return pages * page_size
    except (ValueError, OSError, AttributeError):
        pass
    return None


def _detect_container_runtime() -> str | None:
    """Detect if running inside a container.

    Checks for Docker (/.dockerenv), Podman (/run/.containerenv),
    and Kubernetes (KUBERNETES_SERVICE_HOST env var).
    Returns the runtime name or None if not in a container.
    """
    if os.path.exists("/.dockerenv"):
        return "docker"
    if os.path.exists("/run/.containerenv"):
        return "podman"
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return "kubernetes"
    return None
