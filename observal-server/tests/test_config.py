# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for configuration settings."""


def test_deployment_mode_defaults_to_local():
    """DEPLOYMENT_MODE should default to 'local'."""
    from config import Settings

    s = Settings(
        DATABASE_URL="sqlite+aiosqlite:///",
        SECRET_KEY="test",
    )
    assert s.DEPLOYMENT_MODE == "local"


def test_deployment_mode_accepts_enterprise():
    """DEPLOYMENT_MODE should accept 'enterprise'."""
    from config import Settings

    s = Settings(
        DATABASE_URL="sqlite+aiosqlite:///",
        SECRET_KEY="test",
        DEPLOYMENT_MODE="enterprise",
    )
    assert s.DEPLOYMENT_MODE == "enterprise"


def test_deployment_mode_rejects_invalid():
    """DEPLOYMENT_MODE should reject values other than 'local' or 'enterprise'."""
    import pytest
    from pydantic import ValidationError

    from config import Settings

    with pytest.raises(ValidationError):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///",
            SECRET_KEY="test",
            DEPLOYMENT_MODE="staging",
        )


def test_demo_env_vars_default_to_none():
    """All DEMO_* vars should default to None."""
    from config import Settings

    s = Settings(
        DATABASE_URL="sqlite+aiosqlite:///",
        SECRET_KEY="test",
    )
    assert s.DEMO_SUPER_ADMIN_EMAIL is None
    assert s.DEMO_SUPER_ADMIN_PASSWORD is None
    assert s.DEMO_ADMIN_EMAIL is None
    assert s.DEMO_ADMIN_PASSWORD is None
    assert s.DEMO_REVIEWER_EMAIL is None
    assert s.DEMO_REVIEWER_PASSWORD is None
    assert s.DEMO_USER_EMAIL is None
    assert s.DEMO_USER_PASSWORD is None
