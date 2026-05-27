# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Ensure all package versions stay in sync across the monorepo.

The release script (tools/release.sh) bumps pyproject.toml, observal-server/pyproject.toml,
web/package.json, and packages/pi-extension/package.json together. This test catches
drift if someone bumps one without the others.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _extract_toml_version(path: Path) -> str:
    text = path.read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m, f"No version found in {path}"
    return m.group(1)


def _extract_json_version(path: Path) -> str:
    data = json.loads(path.read_text())
    return data["version"]


def test_all_package_versions_in_sync():
    """All version declarations in the monorepo must match."""
    versions = {}

    # Root pyproject.toml (CLI)
    versions["pyproject.toml"] = _extract_toml_version(ROOT / "pyproject.toml")

    # Server pyproject.toml
    server_toml = ROOT / "observal-server" / "pyproject.toml"
    if server_toml.exists():
        versions["observal-server/pyproject.toml"] = _extract_toml_version(server_toml)

    # Web package.json
    web_pkg = ROOT / "web" / "package.json"
    if web_pkg.exists():
        versions["web/package.json"] = _extract_json_version(web_pkg)

    # Pi extension package.json
    pi_pkg = ROOT / "packages" / "pi-extension" / "package.json"
    if pi_pkg.exists():
        versions["packages/pi-extension/package.json"] = _extract_json_version(pi_pkg)

    unique_versions = set(versions.values())
    assert len(unique_versions) == 1, "Version mismatch across packages. Run tools/release.sh to sync.\n" + "\n".join(
        f"  {k}: {v}" for k, v in sorted(versions.items())
    )
