# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for the DuckDB analytics migration runner."""

import pytest

from services.analytics.duckdb.migrations import (
    MIGRATIONS_DIR,
    MigrationError,
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


def test_checksum_ignores_spdx_and_sql_comments():
    sql = "CREATE TABLE example (id INTEGER);\n"
    marker = "-- SPDX-"
    commented = marker + "License-Identifier: Apache-2.0\n-- explanation\n" + sql

    assert _checksum(commented) == _checksum(sql)


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


async def test_baseline_declares_no_constraints_or_art_indexes(tmp_path):
    """The shipped baseline is the final schema: no PRIMARY KEY, no ART indexes.

    Replay identity lives in ANALYTICS_UPSERT_KEYS (DELETE + INSERT), so a fresh
    database must not carry a constraint-backed index for telemetry tables.
    """
    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", threads=1, read_connections=1)
    await store.start()
    try:
        assert await run_migrations(store) == ["001_baseline"]
        _, constraints = await store.query(
            "SELECT table_name FROM duckdb_constraints() "
            "WHERE constraint_type = 'PRIMARY KEY' AND table_name <> 'analytics_schema_migrations'"
        )
        assert constraints == []
        _, indexes = await store.query(
            "SELECT index_name FROM duckdb_indexes() WHERE table_name <> 'analytics_schema_migrations'"
        )
        assert indexes == []
    finally:
        await store.close()


async def test_upsert_keys_replace_rows_without_a_primary_key(tmp_path):
    """Replay replaces the previous payload for the same line offset."""
    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", threads=1, read_connections=1)
    await store.start()
    try:
        await run_migrations(store)

        def event(raw_line: str) -> dict:
            return {
                "session_id": "session",
                "project_id": "default",
                "user_id": "user",
                "harness": "pi",
                "line_offset": 1,
                "event_type": "user_prompt",
                "timestamp": "2026-01-01 00:00:00.000",
                "raw_line": raw_line,
            }

        await store.insert("session_events", [event("first")])
        await store.insert("session_events", [event("replayed")])
        _, rows = await store.query("SELECT raw_line FROM session_events")
        assert rows == [("replayed",)]
    finally:
        await store.close()


async def test_failed_migration_rolls_back_every_schema_change(tmp_path, monkeypatch):
    monkeypatch.setattr("services.analytics.duckdb.migrations.MIGRATIONS_DIR", tmp_path)
    (tmp_path / "001_broken.sql").write_text(
        "CREATE TABLE must_not_survive (a INTEGER);\nINSERT INTO missing_table VALUES (1);\n"
    )

    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", threads=1, read_connections=1)
    await store.start()
    try:
        with pytest.raises(Exception, match="missing_table"):
            await run_migrations(store)
        _, tables = await store.query(
            "SELECT table_name FROM information_schema.tables WHERE table_name = 'must_not_survive'"
        )
        assert tables == []
        _, applied = await store.query("SELECT version FROM analytics_schema_migrations")
        assert applied == []
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
        with pytest.raises(MigrationError, match="changed after it was applied"):
            await run_migrations(store)
    finally:
        await store.close()
