# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DuckDB storage engine: single-writer connection management.

The service container is the only process that opens the analytics database for
writing.  Within the process a dedicated writer connection serializes all
mutations, while a small pool of read connections serves concurrent queries.
"""

from __future__ import annotations

import asyncio
import fcntl
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import duckdb
import pyarrow as pa
from loguru import logger as optic

from services.analytics.duckdb._settings import (
    ANALYTICS_COLUMN_TYPES,
    ANALYTICS_DEDUPE_KEYS,
    ANALYTICS_LOAD_COLUMN_TYPES,
    ANALYTICS_LOAD_COLUMNS,
    ANALYTICS_TABLES,
    ANALYTICS_TIME_COLUMNS,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# Arrow carriers for DuckDB column types.  Timestamps stay text so DuckDB
# applies exactly the same TIMESTAMP conversion as parameterized inserts, and
# unsigned columns keep their full range (int64 inference would overflow).
_ARROW_TYPES: dict[str, pa.DataType] = {
    "VARCHAR": pa.string(),
    "TIMESTAMP": pa.string(),
    "INTEGER": pa.int32(),
    "BIGINT": pa.int64(),
    "UTINYINT": pa.uint8(),
    "USMALLINT": pa.uint16(),
    "UINTEGER": pa.uint32(),
    "UBIGINT": pa.uint64(),
    "FLOAT": pa.float32(),
    "DOUBLE": pa.float64(),
}


def _arrow_schema(table: str) -> pa.Schema:
    """Explicit Arrow schema for a table's insert columns."""
    types = ANALYTICS_COLUMN_TYPES[table]
    return pa.schema([(column, _ARROW_TYPES[duck_type]) for column, duck_type in types.items()])


# Tables whose primary key makes a write idempotent (DuckDB
# ReplacingMergeTree equivalents).  Everything else is append-only.
UPSERT_TABLES = frozenset({"session_events", "session_checkpoints", "session_stats_agg", "layer_snapshots"})


def _jsonable(value: Any) -> Any:
    """Convert a DuckDB value into something ``orjson`` can serialise."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    return str(value)


def _jsonable_row(row: tuple) -> tuple:
    return tuple(_jsonable(value) for value in row)


class AnalyticsStore:
    """Owns the DuckDB connections behind the analytics service."""

    def __init__(
        self,
        *,
        path: str | Path,
        threads: int = 4,
        memory_limit: str = "",
        read_connections: int = 4,
        query_timeout: float = 60.0,
        max_result_rows: int = 100_000,
    ) -> None:
        self.path = str(path)
        self.threads = threads
        self.memory_limit = memory_limit
        self.read_connections = max(1, read_connections)
        self.query_timeout = query_timeout
        self.max_result_rows = max_result_rows

        self._writer: duckdb.DuckDBPyConnection | None = None
        self._readers: asyncio.Queue[duckdb.DuckDBPyConnection] | None = None
        self._write_lock = asyncio.Lock()
        self._lock_file = None
        self._started = False

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Open connections and apply baseline pragmas."""
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._acquire_process_lock()
        try:
            self._writer = await asyncio.to_thread(self._connect)
        except duckdb.IOException as e:
            raise RuntimeError(
                f"cannot open analytics database at {self.path}: {e}. "
                "The mounted data directory must be writable by the container user (uid 1001)."
            ) from e
        self._readers = asyncio.Queue()
        for _ in range(self.read_connections):
            await self._readers.put(await asyncio.to_thread(self._connect))
        await self.apply_pragmas(self._baseline_pragmas())
        self._started = True
        optic.info(
            "DuckDB analytics store ready (path={}, readers={}, threads={})",
            self.path,
            self.read_connections,
            self.threads,
        )

    async def close(self) -> None:
        for con in self._all_connections():
            try:
                await asyncio.to_thread(con.close)
            except Exception as e:  # pragma: no cover - shutdown best effort
                optic.debug("closing DuckDB connection failed: {}", e)
        self._writer = None
        self._readers = None
        self._started = False
        if self._lock_file is not None:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except OSError:  # pragma: no cover - shutdown best effort
                pass
            self._lock_file = None

    def _acquire_process_lock(self) -> None:
        """Take an exclusive advisory lock next to the database file.

        DuckDB itself refuses a second writer, but failing here gives operators
        a clear, actionable error instead of an opaque I/O error.
        """
        lock_path = Path(f"{self.path}.lock")
        lock_file = lock_path.open("a+")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            lock_file.close()
            raise RuntimeError(
                f"another process already owns the analytics database at {self.path} "
                "(only one DuckDB service may run per data directory)"
            ) from e
        self._lock_file = lock_file

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.path)

    def _baseline_pragmas(self) -> dict[str, str]:
        # DuckDB stores naive UTC in DateTime64; DuckDB would otherwise
        # interpret naive timestamps in the host's local timezone.
        pragmas = {"threads": str(self.threads), "enable_progress_bar": "false"}
        pragmas["TimeZone"] = "UTC"
        if self.memory_limit:
            pragmas["memory_limit"] = self.memory_limit
        return pragmas

    def _all_connections(self) -> list[duckdb.DuckDBPyConnection]:
        connections: list[duckdb.DuckDBPyConnection] = []
        if self._writer is not None:
            connections.append(self._writer)
        if self._readers is not None:
            connections.extend(list(self._readers._queue))
        return connections

    # ── pragmas and admin ────────────────────────────────────────────────────

    async def apply_pragmas(self, pragmas: dict[str, str]) -> None:
        if not pragmas:
            return
        for pragma, value in pragmas.items():
            if not pragma.replace("_", "").isalnum():
                continue
            quoted = value.replace("'", "''")
            statement = f"SET {pragma} = '{quoted}'"
            async with self._write_lock:
                for con in self._all_connections():
                    await asyncio.to_thread(con.execute, statement)

    async def checkpoint(self) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._require_writer().execute, "CHECKPOINT")

    async def backup(self, destination: str) -> None:
        escaped = destination.replace("'", "''")
        async with self._write_lock:
            await asyncio.to_thread(self._require_writer().execute, f"EXPORT DATABASE '{escaped}' (FORMAT PARQUET)")

    # ── queries ──────────────────────────────────────────────────────────────

    async def health(self) -> bool:
        try:
            await self.query("SELECT 1 AS ok")
            return True
        except Exception as e:
            optic.warning("DuckDB health check failed: {}", e)
            return False

    async def schema_version(self) -> str:
        try:
            _, rows = await self.query("SELECT max(version) AS version FROM analytics_schema_migrations")
        except Exception:
            return ""
        return str(rows[0][0]) if rows and rows[0][0] else ""

    async def query(self, sql: str, params: dict | list | None = None) -> tuple[list[str], list[tuple]]:
        con = await self._acquire_reader()
        try:
            return await self._run(con, sql, params, fetch=True)
        finally:
            self._release_reader(con)

    async def execute(self, sql: str, params: dict | list | None = None) -> int:
        async with self._write_lock:
            _, rows = await self._run(self._require_writer(), sql, params, fetch=False)
        if not rows or not rows[0]:
            return 0
        return int(rows[0][0] or 0)

    async def insert(self, table: str, rows: list[dict]) -> int:
        """Insert rows through Arrow, upserting tables that carry a primary key."""
        columns = ANALYTICS_TABLES.get(table)
        if columns is None:
            raise ValueError(f"unknown analytics table: {table}")
        if not rows:
            return 0
        batch = pa.Table.from_pylist(
            [{key: row.get(key) for key in columns} for row in rows],
            schema=_arrow_schema(table),
        )
        verb = "INSERT OR REPLACE" if table in UPSERT_TABLES else "INSERT"
        async with self._write_lock:
            con = self._require_writer()

            def _load() -> int:
                con.register("_analytics_batch", batch)
                try:
                    con.execute(f"{verb} INTO {table} BY NAME SELECT * FROM _analytics_batch")
                finally:
                    con.unregister("_analytics_batch")
                return len(rows)

            return await self._guard(con, _load)

    async def load_parquet(self, table: str, paths: list[str], *, replace: bool = True) -> int:
        """Bulk-load service-local Parquet files into a whitelisted table.

        Column names come from the table registry; values are cast to the
        column's declared type so ClickHouse-exported Parquet files load
        without per-file schema hand-holding.
        """
        columns = ANALYTICS_LOAD_COLUMNS.get(table)
        types = ANALYTICS_LOAD_COLUMN_TYPES.get(table)
        if columns is None or types is None:
            raise ValueError(f"unknown analytics table: {table}")
        if not paths:
            return 0
        escaped_paths = ", ".join("'" + str(path).replace("'", "''") + "'" for path in paths)
        column_list = ", ".join(columns)
        # Declaring the schema makes DuckDB return every target column, with
        # NULLs for columns the exported Parquet files do not carry (DuckDB
        # exports only the columns that existed at export time).
        declared = ", ".join(
            f"'{column}': {{'name': '{column}', 'type': '{types[column]}', 'default_value': NULL}}"
            for column in columns
        )
        verb = "INSERT OR REPLACE" if replace and table in UPSERT_TABLES else "INSERT"
        dedupe_keys = ANALYTICS_DEDUPE_KEYS.get(table)
        delete_sql = ""
        if dedupe_keys:
            matches = " AND ".join(f"incoming.{key} = {table}.{key}" for key in dedupe_keys)
            delete_sql = (
                f"DELETE FROM {table} WHERE EXISTS ("
                f"SELECT 1 FROM read_parquet([{escaped_paths}], schema = MAP {{{declared}}}) AS incoming "
                f"WHERE {matches})"
            )
        insert_sql = (
            f"{verb} INTO {table} ({column_list}) "
            f"SELECT {column_list} FROM read_parquet("
            f"[{escaped_paths}], schema = MAP {{{declared}}})"
        )
        async with self._write_lock:
            con = self._require_writer()

            def _load() -> int:
                before = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                if delete_sql:
                    con.execute(delete_sql)
                con.execute(insert_sql)
                after = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                return int(after - before)

            return await self._guard(con, _load)

    # ── internals ────────────────────────────────────────────────────────────

    def _require_writer(self) -> duckdb.DuckDBPyConnection:
        if self._writer is None:
            raise RuntimeError("analytics store is not started")
        return self._writer

    async def _acquire_reader(self) -> duckdb.DuckDBPyConnection:
        if self._readers is None:
            raise RuntimeError("analytics store is not started")
        return await self._readers.get()

    def _release_reader(self, con: duckdb.DuckDBPyConnection) -> None:
        if self._readers is not None:
            self._readers.put_nowait(con)

    async def _run(
        self,
        con: duckdb.DuckDBPyConnection,
        sql: str,
        params: dict | list | None,
        *,
        fetch: bool,
    ) -> tuple[list[str], list[tuple]]:
        def _work() -> tuple[list[str], list[tuple]]:
            result = con.execute(sql, params) if params else con.execute(sql)
            if not fetch:
                # DuckDB reports the affected-row count as a one-column result
                # set for DML, which is what the /execute contract returns.
                verb = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
                if verb in {"INSERT", "UPDATE", "DELETE", "MERGE", "REPLACE"} and result.description:
                    affected = result.fetchall()
                    count = int(affected[0][0]) if affected and affected[0] and affected[0][0] is not None else 0
                    return [], [(count,)]
                return [], []
            columns = [desc[0] for desc in (result.description or [])]
            rows = result.fetchmany(self.max_result_rows)
            return columns, [_jsonable_row(row) for row in rows]

        return await self._guard(con, _work)

    async def _guard(self, con: duckdb.DuckDBPyConnection, work: Callable[[], object]):
        task = asyncio.create_task(asyncio.to_thread(work))
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=self.query_timeout)
        except (TimeoutError, asyncio.CancelledError) as exc:
            # A cancelled to_thread awaitable does not stop its worker thread.
            # Interrupt it and wait for the thread to leave DuckDB before the
            # caller can return this connection to the reader pool (or release
            # the writer lock). Reusing a still-busy connection can corrupt the
            # next query with a delayed interrupt.
            optic.warning("DuckDB query interrupted after {}s", self.query_timeout)
            await asyncio.to_thread(con.interrupt)
            try:
                await asyncio.shield(task)
            except Exception:
                pass
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise TimeoutError(f"analytics query exceeded {self.query_timeout}s") from None

    async def export_parquet(self, destination: str, tables: list[str] | None = None) -> dict[str, int]:
        """Write each analytics table to monthly Parquet files under *destination*.

        Mirrors the ClickHouse exporter's layout (``<table>_<YYYY>-<MM>.parquet``)
        so the same manifest, import and validation code consume the result.
        Returns per-table row counts.
        """
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        # Every telemetry table travels, including session_stats_agg: the
        # summaries are written by the ingest path, not rebuilt from events on
        # import, so an export that skipped them would leave the target's
        # dashboards empty.
        selected = tables or list(ANALYTICS_TABLES)
        counts: dict[str, int] = {}
        for table in selected:
            columns = ANALYTICS_TABLES.get(table)
            time_column = ANALYTICS_TIME_COLUMNS.get(table)
            if columns is None or time_column is None:
                continue
            async with self._write_lock:
                con = self._require_writer()

                def _export(
                    connection: duckdb.DuckDBPyConnection = con,
                    table_name: str = table,
                    time_col: str = time_column,
                ) -> int:
                    bounds = connection.execute(f"SELECT count(*) AS n FROM {table_name}").fetchone()
                    total = int(bounds[0] or 0)
                    if total == 0:
                        return 0
                    months = connection.execute(
                        f"SELECT DISTINCT strftime(CAST({time_col} AS DATE), '%Y-%m') AS month "
                        f"FROM {table_name} WHERE {time_col} IS NOT NULL ORDER BY month"
                    ).fetchall()
                    for (month,) in months:
                        base = Path(destination) / f"{table_name}_{month}.parquet"
                        escaped = str(base).replace("'", "''")
                        connection.execute(
                            f"COPY (SELECT * FROM {table_name} "
                            f"WHERE strftime(CAST({time_col} AS DATE), '%Y-%m') = '{month}') "
                            f"TO '{escaped}' (FORMAT PARQUET)"
                        )
                    # Rows with a NULL time column would otherwise be counted in
                    # the manifest but never written, so they get their own file.
                    unpartitioned = int(
                        connection.execute(f"SELECT count(*) FROM {table_name} WHERE {time_col} IS NULL").fetchone()[0]
                        or 0
                    )
                    if unpartitioned:
                        base = Path(destination) / f"{table_name}_null.parquet"
                        escaped = str(base).replace("'", "''")
                        connection.execute(
                            f"COPY (SELECT * FROM {table_name} WHERE {time_col} IS NULL) "
                            f"TO '{escaped}' (FORMAT PARQUET)"
                        )
                    return total

                counts[table] = await self._guard(con, _export)
        return counts
