# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for the DuckDB analytics migration runner."""

import pytest

from services.analytics.duckdb.migrations import (
    MIGRATIONS_DIR,
    _checksum,
    _split_sql,
    run_migrations,
)
from services.analytics.duckdb.storage import AnalyticsStore


def test_split_sql_ignores_comments_and_blank_tails():
    statements = _split_sql(
        """
        -- a comment with ; inside
        # another comment
        CREATE TABLE t (a INTEGER);
        INSERT INTO t VALUES (1);
        """
    )

    assert statements == ["CREATE TABLE t (a INTEGER)", "INSERT INTO t VALUES (1)"]


def test_split_sql_respects_quotes():
    statements = _split_sql("INSERT INTO t VALUES ('a;b'); SELECT 1")

    assert statements == ["INSERT INTO t VALUES ('a;b')", "SELECT 1"]


def test_repo_baseline_migration_exists():
    assert (MIGRATIONS_DIR / "001_baseline.sql").exists()


async def test_run_migrations_applies_pending_files(tmp_path, monkeypatch):
    monkeypatch.setattr("services.analytics.duckdb.migrations.MIGRATIONS_DIR", tmp_path)
    (tmp_path / "001_first.sql").write_text("CREATE TABLE one (a INTEGER);\n")
    (tmp_path / "002_second.sql").write_text("CREATE TABLE two (b INTEGER);\n")

    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", threads=1, read_connections=1, query_timeout=5.0)
    await store.start()
    try:
        assert await run_migrations(store) == ["001_first", "002_second"]
        assert await run_migrations(store) == []

        _, rows = await store.query("SELECT version, checksum FROM analytics_schema_migrations ORDER BY version")
        assert [row[0] for row in rows] == ["001_first", "002_second"]
        assert rows[0][1] == _checksum((tmp_path / "001_first.sql").read_text())
    finally:
        await store.close()


async def test_run_migrations_rejects_changed_files(tmp_path, monkeypatch):
    monkeypatch.setattr("services.analytics.duckdb.migrations.MIGRATIONS_DIR", tmp_path)
    migration = tmp_path / "001_first.sql"
    migration.write_text("CREATE TABLE one (a INTEGER);\n")

    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", threads=1, read_connections=1, query_timeout=5.0)
    await store.start()
    try:
        await run_migrations(store)
        migration.write_text("CREATE TABLE one (a INTEGER, b INTEGER);\n")
        with pytest.raises(Exception, match="changed after it was applied"):
            await run_migrations(store)
    finally:
        await store.close()
