# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Detect how the CLI was installed to determine upgrade strategy.

Supports: uv tool, pip, standalone binary (PyInstaller), Homebrew, system package.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class InstallMethod(Enum):
    UV_TOOL = "uv_tool"
    PIP = "pip"
    BINARY = "binary"
    HOMEBREW = "homebrew"
    SYSTEM_PACKAGE = "system"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class InstallInfo:
    method: InstallMethod
    path: Path  # Path to the observal binary/script
    writable: bool  # Whether current user can write to it
    managed_by: str | None  # e.g., "brew", "apt", "uv", "pip"


# Module-level cache (detect once per process)
_cached_info: InstallInfo | None = None


def detect() -> InstallInfo:
    """Detect how observal was installed. Result is cached per-process."""
    global _cached_info
    if _cached_info is not None:
        return _cached_info

    binary_path = Path(shutil.which("observal") or sys.executable).resolve()
    path_str = str(binary_path).lower()

    info = _detect_from_path(binary_path, path_str)
    _cached_info = info
    return info


def _detect_from_path(binary_path: Path, path_str: str) -> InstallInfo:
    """Internal detection logic (separated for testability)."""

    # 1. Homebrew (most specific path check)
    if "/homebrew/" in path_str or "/linuxbrew/" in path_str or "linuxbrew" in path_str:
        return InstallInfo(
            method=InstallMethod.HOMEBREW,
            path=binary_path,
            writable=False,
            managed_by="brew",
        )

    # 2. System package manager (/usr/bin, /usr/sbin)
    if path_str.startswith(("/usr/bin/", "/usr/sbin/")):
        return InstallInfo(
            method=InstallMethod.SYSTEM_PACKAGE,
            path=binary_path,
            writable=os.access(binary_path, os.W_OK),
            managed_by=_detect_system_pkg_mgr(),
        )

    # 3. Standalone binary (PyInstaller frozen)
    if getattr(sys, "frozen", False):
        return InstallInfo(
            method=InstallMethod.BINARY,
            path=binary_path,
            writable=os.access(binary_path, os.W_OK),
            managed_by=None,
        )

    # 4. uv tool (fast path: check if under uv tool directory)
    uv_tool_dir = Path.home() / ".local" / "share" / "uv" / "tools"
    if str(binary_path).startswith(str(uv_tool_dir)):
        return InstallInfo(
            method=InstallMethod.UV_TOOL,
            path=binary_path,
            writable=True,
            managed_by="uv",
        )

    # 5. uv tool (slow path: ask uv)
    if _check_uv_tool_list():
        return InstallInfo(
            method=InstallMethod.UV_TOOL,
            path=binary_path,
            writable=True,
            managed_by="uv",
        )

    # 6. Default: assume pip
    return InstallInfo(
        method=InstallMethod.PIP,
        path=binary_path,
        writable=os.access(binary_path.parent, os.W_OK),
        managed_by="pip",
    )


def _check_uv_tool_list() -> bool:
    """Check if observal-cli is in uv tool list output."""
    try:
        r = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.returncode == 0 and "observal-cli" in r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _detect_system_pkg_mgr() -> str | None:
    """Detect which system package manager owns the observal binary."""
    checks = [
        (["dpkg", "-S", "observal"], "apt"),
        (["rpm", "-qf", "/usr/bin/observal"], "dnf"),
    ]
    for cmd, name in checks:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=3)
            if r.returncode == 0:
                return name
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return None
