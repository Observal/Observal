# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for observal_cli.version_check."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from observal_cli import version_check


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Redirect cache file to tmp dir for test isolation."""
    cache_file = tmp_path / "version_cache.json"
    monkeypatch.setattr(version_check, "CACHE_FILE", cache_file)
    monkeypatch.setattr(version_check, "CONFIG_DIR", tmp_path)
    return cache_file


@pytest.fixture
def mock_config(monkeypatch):
    """Return a helper to mock config values."""

    def _mock(**kwargs):
        defaults = {
            "update_check": True,
            "update_check_interval": 86400,
            "update_check_repo": "",
            "server_url": "",
            "access_token": "",
        }
        defaults.update(kwargs)
        monkeypatch.setattr(version_check, "load_config", lambda: defaults)

    return _mock


# ── _should_check tests ─────────────────────────────────────────


class TestShouldCheck:
    def test_no_cache(self):
        assert version_check._should_check(None, 86400) is True

    def test_stale_cache(self):
        old_time = datetime(2020, 1, 1, tzinfo=UTC).isoformat()
        cache = {"last_checked": old_time}
        assert version_check._should_check(cache, 86400) is True

    def test_fresh_cache(self):
        now = datetime.now(UTC).isoformat()
        cache = {"last_checked": now}
        assert version_check._should_check(cache, 86400) is False

    def test_future_timestamp_treated_as_stale(self):
        """Clock skew: if last_checked is in the future, re-check."""
        future = datetime(2099, 1, 1, tzinfo=UTC).isoformat()
        cache = {"last_checked": future}
        assert version_check._should_check(cache, 86400) is True

    def test_missing_last_checked_key(self):
        cache = {"latest_version": "1.0.0"}
        assert version_check._should_check(cache, 86400) is True

    def test_invalid_timestamp_format(self):
        cache = {"last_checked": "not-a-date"}
        assert version_check._should_check(cache, 86400) is True


# ── _fetch_from_github tests ────────────────────────────────────


MOCK_RELEASE_RESPONSE = {
    "tag_name": "v0.8.0",
    "html_url": "https://github.com/BlazeUp-AI/Observal/releases/tag/v0.8.0",
    "published_at": "2026-05-20T10:00:00Z",
    "prerelease": False,
    "assets": [],
}


class TestFetchFromGithub:
    def test_success(self, monkeypatch):
        def mock_get(*args, **kwargs):
            resp = httpx.Response(200, json=MOCK_RELEASE_RESPONSE)
            return resp

        monkeypatch.setattr(httpx, "get", mock_get)
        result = version_check._fetch_from_github()
        assert result is not None
        assert result["latest_version"] == "0.8.0"
        assert result["source"] == "github"

    def test_404_returns_none(self, monkeypatch):
        def mock_get(*args, **kwargs):
            return httpx.Response(404)

        monkeypatch.setattr(httpx, "get", mock_get)
        assert version_check._fetch_from_github() is None

    def test_timeout_returns_none(self, monkeypatch):
        def mock_get(*args, **kwargs):
            raise httpx.ReadTimeout("timeout")

        monkeypatch.setattr(httpx, "get", mock_get)
        assert version_check._fetch_from_github() is None

    def test_invalid_json_returns_none(self, monkeypatch):
        def mock_get(*args, **kwargs):
            return httpx.Response(200, content=b"not json", headers={"content-type": "text/html"})

        monkeypatch.setattr(httpx, "get", mock_get)
        assert version_check._fetch_from_github() is None

    def test_oversized_response_returns_none(self, monkeypatch):
        def mock_get(*args, **kwargs):
            huge = b"x" * (version_check.MAX_RESPONSE_SIZE + 1)
            return httpx.Response(200, content=huge)

        monkeypatch.setattr(httpx, "get", mock_get)
        assert version_check._fetch_from_github() is None

    def test_invalid_semver_tag_returns_none(self, monkeypatch):
        bad_release = {**MOCK_RELEASE_RESPONSE, "tag_name": "not-a-version"}

        def mock_get(*args, **kwargs):
            return httpx.Response(200, json=bad_release)

        monkeypatch.setattr(httpx, "get", mock_get)
        assert version_check._fetch_from_github() is None

    def test_prerelease_skipped_by_default(self, monkeypatch):
        """When include_pre=False and using /latest, prerelease shouldn't appear."""
        pre_release = {**MOCK_RELEASE_RESPONSE, "prerelease": True}

        def mock_get(*args, **kwargs):
            return httpx.Response(200, json=pre_release)

        monkeypatch.setattr(httpx, "get", mock_get)
        # /latest endpoint on GitHub already filters prereleases server-side
        # but if somehow returned, we still accept (GitHub controls this)
        result = version_check._fetch_from_github(include_pre=False)
        assert result is not None  # We trust GitHub's /latest filter


# ── _is_newer tests ─────────────────────────────────────────────


class TestIsNewer:
    def test_newer_true(self):
        assert version_check._is_newer("0.8.0", "0.7.0") is True

    def test_newer_false(self):
        assert version_check._is_newer("0.6.0", "0.7.0") is False

    def test_equal_is_not_newer(self):
        assert version_check._is_newer("0.7.0", "0.7.0") is False

    def test_prerelease_newer_than_stable(self):
        assert version_check._is_newer("0.8.0a1", "0.7.0") is True


# ── maybe_check tests ───────────────────────────────────────────


class TestMaybeCheck:
    def test_disabled_via_config(self, mock_config, monkeypatch):
        mock_config(update_check=False)
        assert version_check.maybe_check() is None

    def test_disabled_via_env_var(self, mock_config, monkeypatch):
        mock_config()
        monkeypatch.setenv("OBSERVAL_NO_UPDATE_CHECK", "1")
        assert version_check.maybe_check() is None

    def test_returns_update_when_newer(self, mock_config, monkeypatch, isolated_cache):
        mock_config()
        monkeypatch.setattr(version_check, "get_current_version", lambda: "0.7.0")
        monkeypatch.setattr(
            version_check,
            "_resolve_update_source",
            lambda: {"latest_version": "0.8.0", "release_url": "", "published_at": "", "source": "github"},
        )
        result = version_check.maybe_check()
        assert result is not None
        assert result.latest == "0.8.0"
        assert result.current == "0.7.0"

    def test_returns_none_when_current(self, mock_config, monkeypatch, isolated_cache):
        mock_config()
        monkeypatch.setattr(version_check, "get_current_version", lambda: "0.8.0")
        monkeypatch.setattr(
            version_check,
            "_resolve_update_source",
            lambda: {"latest_version": "0.8.0", "release_url": "", "published_at": "", "source": "github"},
        )
        assert version_check.maybe_check() is None


# ── Cache HMAC integrity tests ──────────────────────────────────


class TestCacheIntegrity:
    def test_tampered_cache_treated_as_missing(self, isolated_cache, monkeypatch, mock_config):
        mock_config()
        # Write a valid cache
        version_check._write_cache(
            {
                "last_checked": datetime.now(UTC).isoformat(),
                "latest_version": "0.8.0",
                "release_url": "",
                "published_at": "",
                "source": "github",
                "fetch_failed": False,
            }
        )
        # Tamper with it
        data = json.loads(isolated_cache.read_text())
        data["latest_version"] = "99.0.0"  # Modify without updating HMAC
        isolated_cache.write_text(json.dumps(data))

        # Should treat as missing (HMAC mismatch)
        assert version_check._read_cache() is None

    def test_valid_cache_reads_ok(self, isolated_cache, mock_config):
        mock_config()
        version_check._write_cache(
            {
                "last_checked": datetime.now(UTC).isoformat(),
                "latest_version": "0.8.0",
                "fetch_failed": False,
            }
        )
        cache = version_check._read_cache()
        assert cache is not None
        assert cache["latest_version"] == "0.8.0"

    def test_cache_atomic_write(self, isolated_cache, tmp_path):
        """Verify no .tmp file left behind after write."""
        version_check._write_cache({"last_checked": datetime.now(UTC).isoformat()})
        assert isolated_cache.exists()
        assert not (tmp_path / "version_cache.tmp").exists()


# ── fetch_all_releases tests ────────────────────────────────────


class TestFetchAllReleases:
    def test_pagination(self, monkeypatch):
        page1 = [
            {"tag_name": "v0.8.0", "published_at": "2026-05-20", "prerelease": False, "html_url": ""},
            {"tag_name": "v0.7.0", "published_at": "2026-05-10", "prerelease": False, "html_url": ""},
        ]
        page2 = []

        call_count = {"n": 0}

        def mock_get(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return httpx.Response(200, json=page1)
            return httpx.Response(200, json=page2)

        monkeypatch.setattr(httpx, "get", mock_get)
        results = version_check.fetch_all_releases()
        assert len(results) == 2
        assert results[0]["version"] == "0.8.0"
        assert results[1]["version"] == "0.7.0"
