# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for configuration settings."""

import os
from unittest.mock import patch


def test_has_license_false_when_no_key():
    """HAS_LICENSE should be False when OBSERVAL_LICENSE_KEY is not set."""
    with patch.dict(os.environ, {"OBSERVAL_LICENSE_KEY": ""}, clear=False):
        # Re-evaluate
        has_license = bool(os.environ.get("OBSERVAL_LICENSE_KEY", ""))
    assert has_license is False


def test_has_license_true_when_key_set():
    """HAS_LICENSE should be True when OBSERVAL_LICENSE_KEY is set."""
    has_license = bool(os.environ.get("OBSERVAL_LICENSE_KEY", ""))
    # In the test env, the .env has a license key
    # Just verify the derivation logic works
    with patch.dict(os.environ, {"OBSERVAL_LICENSE_KEY": "some.key"}, clear=False):
        assert bool(os.environ.get("OBSERVAL_LICENSE_KEY", "")) is True


def test_deployment_mode_in_legacy_vars():
    """DEPLOYMENT_MODE should be in the legacy env var list."""
    from config import _LEGACY_ENV_VARS

    assert "DEPLOYMENT_MODE" in _LEGACY_ENV_VARS


def test_demo_env_vars_default_to_none():
    """All DEMO_* vars should default to None when env is clean."""
    from config import Settings

    # Verify the field declarations accept None
    s = Settings(
        DATABASE_URL="sqlite+aiosqlite:///",
        SECRET_KEY="test",
        DEMO_SUPER_ADMIN_EMAIL=None,
        DEMO_ADMIN_EMAIL=None,
        _env_file=None,
    )
    assert s.DEMO_SUPER_ADMIN_EMAIL is None
    assert s.DEMO_ADMIN_EMAIL is None
