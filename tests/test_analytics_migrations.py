# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for the DuckDB analytics migration runner."""

import shutil

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


async def test_primary_index_removal_preserves_existing_telemetry(tmp_path, monkeypatch):
    source_dir = MIGRATIONS_DIR
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    for name in ("001_baseline.sql", "002_query_indexes.sql", "003_remove_secondary_art_indexes.sql"):
        shutil.copy(source_dir / name, migration_dir / name)
    monkeypatch.setattr("services.analytics.duckdb.migrations.MIGRATIONS_DIR", migration_dir)

    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", threads=1, read_connections=1)
    await store.start()
    try:
        await run_migrations(store)
        await store.insert(
            "session_events",
            [
                {
                    "session_id": "session",
                    "project_id": "default",
                    "user_id": "user",
                    "harness": "pi",
                    "line_offset": 1,
                    "event_type": "user_prompt",
                    "timestamp": "2026-01-01 00:00:00.000",
                    "raw_line": "preserved",
                }
            ],
        )

        shutil.copy(source_dir / "004_remove_primary_art_indexes.sql", migration_dir)
        assert await run_migrations(store) == ["004_remove_primary_art_indexes"]
        _, rows = await store.query("SELECT raw_line FROM session_events")
        assert rows == [("preserved",)]
        _, constraints = await store.query(
            "SELECT table_name FROM duckdb_constraints() "
            "WHERE constraint_type = 'PRIMARY KEY' AND table_name IN "
            "('session_events', 'session_checkpoints', 'session_stats_agg', 'layer_snapshots')"
        )
        assert constraints == []
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


async def test_run_migrations_accepts_and_normalizes_legacy_raw_checksum(tmp_path, monkeypatch):
    import hashlib

    monkeypatch.setattr("services.analytics.duckdb.migrations.MIGRATIONS_DIR", tmp_path)
    migration = tmp_path / "001_first.sql"
    text = "-- old comment\nCREATE TABLE one (a INTEGER);\n"
    migration.write_text(text)

    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", threads=1, read_connections=1)
    await store.start()
    try:
        await store.execute(
            "CREATE TABLE analytics_schema_migrations ("
            "version VARCHAR PRIMARY KEY, name VARCHAR, checksum VARCHAR, applied_at TIMESTAMP DEFAULT now())"
        )
        await store.execute(
            "INSERT INTO analytics_schema_migrations (version, name, checksum) VALUES ($version, $name, $checksum)",
            {"version": "001_first", "name": migration.name, "checksum": hashlib.sha256(text.encode()).hexdigest()},
        )

        assert await run_migrations(store) == []
        _, rows = await store.query("SELECT checksum FROM analytics_schema_migrations WHERE version = '001_first'")
        assert rows == [(_checksum(text),)]

        migration.write_text("-- new SPDX/header comment\n" + text)
        assert await run_migrations(store) == []
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
