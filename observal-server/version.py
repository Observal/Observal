# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Server version detection utility.

Shared between the version middleware and the /config/version endpoint.
"""

from __future__ import annotations

import re
from functools import lru_cache
from importlib.metadata import version as pkg_version
from pathlib import Path


@lru_cache(maxsize=1)
def get_server_version() -> str:
    """Get the server version string.

    Resolution order:
    1. importlib.metadata (installed package)
    2. pyproject.toml (running from source in Docker)
    3. "dev" fallback
    """
    try:
        return pkg_version("observal-server")
    except Exception:
        pass
    try:
        pyproject = Path(__file__).resolve().parent / "pyproject.toml"
        if pyproject.exists():
            m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(), re.M)
            if m:
                return m.group(1)
    except Exception:
        pass
    return "dev"
