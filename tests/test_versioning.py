# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the semver versioning utilities."""

from __future__ import annotations

from services.versioning import bump_version, parse_semver, suggest_versions, validate_semver


class TestParseSemver:
    def test_valid_version(self):
        assert parse_semver("1.0.0") == (1, 0, 0)
        assert parse_semver("0.1.0") == (0, 1, 0)
        assert parse_semver("12.34.56") == (12, 34, 56)

    def test_invalid_version(self):
        assert parse_semver("1.0") is None
        assert parse_semver("v1.0.0") is None
        assert parse_semver("1.0.0-beta") is None
        assert parse_semver("abc") is None
        assert parse_semver("") is None

    def test_zero_version(self):
        assert parse_semver("0.0.0") == (0, 0, 0)


class TestValidateSemver:
    def test_valid(self):
        assert validate_semver("1.0.0") is True
        assert validate_semver("0.1.0") is True

    def test_invalid(self):
        assert validate_semver("1.0") is False
        assert validate_semver("nope") is False


class TestBumpVersion:
    def test_patch(self):
        assert bump_version("1.0.0", "patch") == "1.0.1"
        assert bump_version("1.2.3", "patch") == "1.2.4"

    def test_minor(self):
        assert bump_version("1.0.0", "minor") == "1.1.0"
        assert bump_version("1.2.3", "minor") == "1.3.0"

    def test_major(self):
        assert bump_version("1.0.0", "major") == "2.0.0"
        assert bump_version("1.2.3", "major") == "2.0.0"

    def test_invalid_input_returns_default(self):
        assert bump_version("garbage", "patch") == "1.0.0"

    def test_beta_version_bump(self):
        assert bump_version("0.1.0", "patch") == "0.1.1"
        assert bump_version("0.1.0", "minor") == "0.2.0"
        assert bump_version("0.1.0", "major") == "1.0.0"


class TestSuggestVersions:
    def test_suggestions(self):
        result = suggest_versions("1.2.3")
        assert result == {"patch": "1.2.4", "minor": "1.3.0", "major": "2.0.0"}

    def test_initial_version(self):
        result = suggest_versions("1.0.0")
        assert result == {"patch": "1.0.1", "minor": "1.1.0", "major": "2.0.0"}
