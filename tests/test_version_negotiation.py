# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for version negotiation logic."""

from __future__ import annotations

import pytest

from observal_cli.features import FEATURE_VERSIONS, available_set, is_available


class TestEffectiveVersionMin:
    def test_min_of_cli_and_server(self):
        """effective = min(cli, server)"""
        from packaging.version import Version

        cli = "0.8.0"
        server = "0.6.0"
        effective = str(min(Version(cli), Version(server)))
        assert effective == "0.6.0"

    def test_min_same_version(self):
        from packaging.version import Version

        effective = str(min(Version("0.7.0"), Version("0.7.0")))
        assert effective == "0.7.0"

    def test_min_cli_older(self):
        from packaging.version import Version

        effective = str(min(Version("0.5.0"), Version("0.8.0")))
        assert effective == "0.5.0"


class TestFeatureGating:
    def test_feature_available_at_version(self):
        assert is_available("agent_insights", "0.7.0") is True
        assert is_available("agent_insights", "0.8.0") is True

    def test_feature_not_available_below_version(self):
        assert is_available("agent_insights", "0.6.0") is False
        assert is_available("agent_builder", "0.7.0") is False

    def test_unknown_feature_assumed_available(self):
        assert is_available("nonexistent_feature", "0.1.0") is True

    def test_available_set_at_version(self):
        features = available_set("0.6.0")
        assert "basic_agents" in features
        assert "component_versions" in features
        assert "agent_insights" not in features
        assert "agent_builder" not in features


class TestServerSupports:
    def test_server_supports_checks_effective(self, monkeypatch):
        """server_supports() uses min(cli, server) for gating."""
        monkeypatch.setattr("observal_cli.client._server_version_cache", "0.6.0")
        monkeypatch.setattr("observal_cli.client._get_cli_version", lambda: "0.8.0")

        from observal_cli.client import server_supports

        # agent_insights requires 0.7.0 — effective is 0.6.0 → not available
        assert server_supports("agent_insights") is False
        # basic_agents requires 0.5.0 — effective is 0.6.0 → available
        assert server_supports("basic_agents") is True


class TestHeaderSpoofingSafe:
    def test_spoofed_low_version_reduces_features(self):
        """Spoofing a low CLI version just means less data, not broken data."""
        from packaging.version import Version

        # Attacker sends X-Observal-CLI-Version: 0.1.0
        spoofed_cli = "0.1.0"
        server = "0.8.0"
        effective = str(min(Version(spoofed_cli), Version(server)))
        assert effective == "0.1.0"

        # At effective 0.1.0, almost no features are available
        features = available_set(effective)
        # This is safe — server returns less data, not broken data
        assert "agent_builder" not in features
        assert "agent_insights" not in features


class TestFeatureRegistryIntegrity:
    def test_all_versions_are_valid_semver(self):
        from packaging.version import InvalidVersion, Version

        for feature, ver in FEATURE_VERSIONS.items():
            try:
                Version(ver)
            except InvalidVersion:
                pytest.fail(f"Feature '{feature}' has invalid version: {ver}")

    def test_registry_not_empty(self):
        assert len(FEATURE_VERSIONS) > 0
