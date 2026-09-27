# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import os
import sys
import tempfile
from pathlib import Path

# Run every test against a throwaway home. CLI modules resolve ~/.observal and the
# harness config directories when they are imported, so a test that forgets to
# patch one must still never write the developer's real config, lockfile, or
# harness settings. Set before anything imports observal_cli.
os.environ["HOME"] = os.environ["USERPROFILE"] = tempfile.mkdtemp(prefix="observal-test-home-")

# Add server source to path so `from config import settings` works
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "observal-server"))
sys.path.insert(0, str(ROOT / "packages" / "observal-shared"))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_capability_lock(tmp_path, monkeypatch):
    """Keep every test away from the developer's real ~/.observal/capability_lock.jsonl.

    Install paths and session upload both touch the lock as a side effect, so a
    test that exercises them would otherwise leave fixture data in the real file.
    """
    from observal_cli import capability_lock

    monkeypatch.setattr(capability_lock, "LOCK_PATH", tmp_path / "capability_lock.jsonl")
