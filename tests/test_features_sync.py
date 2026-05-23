# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Ensure Python and TypeScript feature registries are in sync."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from observal_cli.features import FEATURE_VERSIONS

TS_FILE = Path(__file__).resolve().parent.parent / "web" / "src" / "lib" / "features.ts"


def _to_camel_case(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


class TestFeaturesSync:
    def test_typescript_matches_python(self):
        """TypeScript features.ts must contain all features from Python."""
        if not TS_FILE.exists():
            pytest.skip("features.ts not generated yet (run scripts/sync_features.py)")

        content = TS_FILE.read_text()

        for py_name, py_version in FEATURE_VERSIONS.items():
            ts_name = _to_camel_case(py_name)
            # Check the feature is in the TS file with correct version
            pattern = rf'{ts_name}:\s*"{re.escape(py_version)}"'
            assert re.search(pattern, content), (
                f"Feature '{py_name}' (TS: '{ts_name}') with version '{py_version}' "
                f"not found in {TS_FILE}. Run: python scripts/sync_features.py"
            )

    def test_no_extra_typescript_features(self):
        """TypeScript should not have features not in Python."""
        if not TS_FILE.exists():
            pytest.skip("features.ts not generated yet")

        content = TS_FILE.read_text()
        # Extract all feature entries from TS
        ts_features = set(re.findall(r'(\w+):\s*"[\d.]+"', content))
        py_features_camel = {_to_camel_case(k) for k in FEATURE_VERSIONS}

        extra = ts_features - py_features_camel
        assert not extra, f"TypeScript has features not in Python: {extra}. Regenerate: python scripts/sync_features.py"
