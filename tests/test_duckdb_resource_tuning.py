# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for DuckDB resource tuning - admin-configured memory/thread limits,
override swaps, invalid inputs, and live pragma application.

DuckDB applies limits at the connection level (SET memory_limit / threads)
rather than per query; spilling is automatic once memory_limit is set.
"""

import pytest


@pytest.fixture()
def duckdb_con(tmp_path, monkeypatch):
    from config import settings
    from services.duckdb import close_con

    close_con()
    monkeypatch.setattr(settings, "DUCKDB_PATH", str(tmp_path / "tuning.duckdb"))
    monkeypatch.setattr(settings, "DUCKDB_READ_ONLY", False)
    yield
    close_con()


@pytest.fixture(autouse=True)
def _reset_overrides():
    import services.duckdb._settings as st

    saved = dict(st._resource_overrides)
    yield
    st._resource_overrides.clear()
    st._resource_overrides.update(saved)


async def _apply(overrides):
    import services.duckdb as ddb

    await ddb.apply_resource_settings(overrides=overrides)


def _overrides():
    import services.duckdb._settings as st

    return dict(st._resource_overrides)


class TestApplyResourceSettings:
    async def test_valid_memory_override(self, duckdb_con):
        await _apply({"resource.max_query_memory_mb": "300"})
        assert _overrides() == {"memory_limit": "300"}

    async def test_threads_override(self, duckdb_con):
        await _apply({"resource.threads": "4"})
        assert _overrides() == {"threads": "4"}

    async def test_pragma_reaches_the_connection(self, duckdb_con):
        """The SET actually lands on the live DuckDB connection."""
        from services.duckdb import _query

        await _apply({"resource.max_query_memory_mb": "256", "resource.threads": "3"})
        # DuckDB renders 256 MB (decimal) as 244.1 MiB (binary).
        resp = await _query("SELECT current_setting('memory_limit') AS mem")
        resp.raise_for_status()
        assert resp.json()["data"][0]["mem"] == "244.1 MiB"
        resp = await _query("SELECT current_setting('threads')::INTEGER AS t")
        resp.raise_for_status()
        assert resp.json()["data"][0]["t"] == 3

    async def test_zero_value_ignored(self, duckdb_con):
        await _apply({"resource.max_query_memory_mb": "0"})
        assert _overrides() == {}

    async def test_negative_value_ignored(self, duckdb_con):
        await _apply({"resource.max_query_memory_mb": "-100"})
        assert _overrides() == {}

    async def test_non_numeric_value_ignored(self, duckdb_con):
        await _apply({"resource.max_query_memory_mb": "not-a-number"})
        assert _overrides() == {}

    async def test_empty_string_ignored(self, duckdb_con):
        await _apply({"resource.max_query_memory_mb": ""})
        assert _overrides() == {}

    async def test_unknown_key_ignored(self, duckdb_con):
        await _apply({"resource.unknown_setting": "100"})
        assert _overrides() == {}

    async def test_empty_overrides_no_change(self, duckdb_con):
        await _apply({})
        assert _overrides() == {}

    async def test_swap_replaces_previous(self, duckdb_con):
        await _apply({"resource.max_query_memory_mb": "400"})
        assert _overrides()["memory_limit"] == "400"
        await _apply({"resource.max_query_memory_mb": "200"})
        assert _overrides()["memory_limit"] == "200"

    async def test_swap_removes_dropped_keys(self, duckdb_con):
        await _apply({"resource.max_query_memory_mb": "400", "resource.threads": "2"})
        assert len(_overrides()) == 2
        await _apply({"resource.max_query_memory_mb": "400"})
        assert _overrides() == {"memory_limit": "400"}
