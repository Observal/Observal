# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Semantic versioning utilities for agent version management."""

from __future__ import annotations

import hashlib
import re

from loguru import logger as optic

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def compute_integrity_hash(content: str) -> str:
    """Compute sha256 integrity hash for lock file entries."""
    optic.trace("computing integrity hash for {} bytes", len(content))
    digest = hashlib.sha256(content.encode()).hexdigest()
    return f"sha256-{digest}"


def parse_semver(version: str) -> tuple[int, int, int] | None:
    optic.trace("parsing semver: {}", version)
    m = SEMVER_RE.match(version)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def validate_semver(version: str) -> bool:
    optic.trace("parsing semver: {}", version)
    return SEMVER_RE.match(version) is not None


def bump_version(current: str, bump_type: str) -> str:
    optic.trace("bumping {} by {}", current, bump_type)
    parsed = parse_semver(current)
    if not parsed:
        return "1.0.0"
    major, minor, patch = parsed
    if bump_type == "major":
        return f"{major + 1}.0.0"
    if bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def suggest_versions(current: str) -> dict[str, str]:
    optic.trace("suggesting next versions from {}", current)
    return {t: bump_version(current, t) for t in ("patch", "minor", "major")}
