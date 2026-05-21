# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for data retention API endpoints."""

import pytest

from schemas.retention import RetentionConfigUpdate


def test_schema_validation_days_too_low():
    """data_retention_days must be >= 7."""
    with pytest.raises(ValueError, match="data_retention_days must be >= 7"):
        RetentionConfigUpdate(retention_enabled=True, data_retention_days=3)


def test_schema_validation_score_too_low():
    """score_retention_days must be >= 7."""
    with pytest.raises(ValueError, match="score_retention_days must be >= 7"):
        RetentionConfigUpdate(retention_enabled=True, data_retention_days=14, score_retention_days=5)


def test_schema_validation_score_less_than_trace():
    """score_retention_days must be >= data_retention_days."""
    with pytest.raises(ValueError, match="score_retention_days must be >= data_retention_days"):
        RetentionConfigUpdate(retention_enabled=True, data_retention_days=60, score_retention_days=30)


def test_schema_validation_max_trace_too_low():
    """max_trace_count must be >= 1000."""
    with pytest.raises(ValueError, match="max_trace_count must be >= 1000"):
        RetentionConfigUpdate(retention_enabled=True, data_retention_days=14, max_trace_count=500)


def test_schema_validation_enable_requires_threshold():
    """Enabling retention requires at least one threshold."""
    with pytest.raises(ValueError, match="At least one"):
        RetentionConfigUpdate(retention_enabled=True)


def test_schema_valid_config():
    """Valid configuration passes validation."""
    config = RetentionConfigUpdate(
        retention_enabled=True,
        data_retention_days=14,
        score_retention_days=30,
        max_trace_count=5000,
    )
    assert config.retention_enabled is True
    assert config.data_retention_days == 14


def test_schema_disable_no_thresholds_needed():
    """Disabling retention doesn't require thresholds."""
    config = RetentionConfigUpdate(retention_enabled=False)
    assert config.retention_enabled is False


def test_schema_enable_with_only_max_count():
    """Enabling with only max_trace_count (no days) is valid."""
    config = RetentionConfigUpdate(retention_enabled=True, max_trace_count=10000)
    assert config.max_trace_count == 10000
