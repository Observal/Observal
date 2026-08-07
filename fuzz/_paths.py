# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Source-tree bootstrap shared by every fuzz target.

Fuzz targets run as standalone scripts, both from a checkout and from the
PyInstaller bundle OSS-Fuzz builds. ``observal_cli`` and ``observal_shared``
ship as installed packages, but ``observal-server`` is only ever placed on
``sys.path`` -- the same arrangement ``tests/conftest.py`` uses.

Every entry is skipped when it does not exist, so this is a no-op inside the
frozen bundle where the modules are already embedded.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_SOURCE_ROOTS = (
    _REPO_ROOT,
    _REPO_ROOT / "observal-server",
    _REPO_ROOT / "packages" / "observal-shared",
)


def add_source_roots() -> None:
    """Prepend the in-tree package roots to ``sys.path``."""
    for root in _SOURCE_ROOTS:
        path = str(root)
        if root.is_dir() and path not in sys.path:
            sys.path.insert(0, path)
