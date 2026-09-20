# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
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
import re
import shutil
from datetime import UTC, date, datetime, time, timedelta
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
    ANALYTICS_UPSERT_KEYS,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_DML_VERBS = frozenset({"INSERT", "UPDATE", "DELETE", "MERGE", "REPLACE"})
# Export file names are built from caller-supplied table names and from the
# partition directory DuckDB creates. Both are rebuilt from these patterns
# before they touch a path, so no raw caller string ever reaches the filesystem.
_SAFE_PATH_COMPONENT = re.compile(r"\A[A-Za-z0-9_]+\Z")
_SAFE_MONTH = re.compile(r"\A\d{4}-\d{2}\Z")
_SQL_NOISE = (
    re.compile(r"'(?:[^']|'')*'"),
    re.compile(r'"(?:[^"]|"")*"'),
    re.compile(r"--[^\n]*"),
    re.compile(r"/\*.*?\*/", re.DOTALL),
)


def _statement_verb(sql: str) -> str:
    """Return the statement's verb, looking through a leading WITH clause.

    ``/execute`` reports an affected-row count only for DML; a naive first-token
    check misses ``WITH ... DELETE`` (and would be fooled by a verb inside a
    string literal or comment).
    """
    stripped = sql
    for pattern in _SQL_NOISE:
        stripped = pattern.sub(" ", stripped)
    tokens = re.findall(r"[A-Za-z_]+", stripped)
    if not tokens:
        return ""
    if tokens[0].upper() != "WITH":
        return tokens[0].upper()
    return next((token.upper() for token in tokens[1:] if token.upper() in _DML_VERBS), "WITH")


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


def _jsonable(value: Any) -> Any:
    """Convert a DuckDB value into something ``orjson`` can serialise."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        # Preserve the ClickHouse HTTP contract: UTC, space separator, and
        # fixed millisecond precision without an explicit offset.
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value.strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    if isinstance(value, date | time):
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
        self._reader_connections: list[duckdb.DuckDBPyConnection] = []
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
            connection = await asyncio.to_thread(self._connect)
            self._reader_connections.append(connection)
            await self._readers.put(connection)
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
        self._reader_connections.clear()
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
        # Analytics timestamps are normalized to naive UTC; DuckDB would
        # otherwise interpret them in the host's local timezone.
        pragmas = {"threads": str(self.threads), "enable_progress_bar": "false"}
        pragmas["TimeZone"] = "UTC"
        if self.memory_limit:
            pragmas["memory_limit"] = self.memory_limit
        return pragmas

    def _all_connections(self) -> list[duckdb.DuckDBPyConnection]:
        connections: list[duckdb.DuckDBPyConnection] = []
        if self._writer is not None:
            connections.append(self._writer)
        # Readers are tracked explicitly: a connection checked out of the pool
        # still needs the pragmas (TimeZone is per-connection) and must be
        # closed on shutdown, and asyncio.Queue._queue is private API.
        connections.extend(self._reader_connections)
        return connections

    # ── pragmas and admin ────────────────────────────────────────────────────

    async def apply_pragmas(self, pragmas: dict[str, str]) -> list[str]:
        """Apply settings to the writer and every reader connection.

        Returns the names that were applied. Names that are not plain
        identifiers are skipped - they cannot be interpolated into SET - so
        callers can report exactly what took effect.
        """
        if not pragmas:
            return []
        applied: list[str] = []
        for pragma, value in pragmas.items():
            if not pragma.replace("_", "").isalnum():
                optic.warning("skipping analytics pragma with an invalid name: {}", pragma)
                continue
            quoted = value.replace("'", "''")
            statement = f"SET {pragma} = '{quoted}'"
            async with self._write_lock:
                for con in self._all_connections():
                    await asyncio.to_thread(con.execute, statement)
            applied.append(pragma)
        return applied

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

    async def execute(
        self,
        sql: str,
        params: dict | list | None = None,
        *,
        enforce_timeout: bool = True,
    ) -> int:
        async with self._write_lock:
            _, rows = await self._run(self._require_writer(), sql, params, fetch=False, enforce_timeout=enforce_timeout)
        if not rows or not rows[0]:
            return 0
        return int(rows[0][0] or 0)

    async def insert(self, table: str, rows: list[dict]) -> int:
        """Insert rows through Arrow, replacing prior rows for upsert-keyed tables."""
        columns = ANALYTICS_TABLES.get(table)
        if columns is None:
            raise ValueError(f"unknown analytics table: {table}")
        if not rows:
            return 0
        upsert_keys = ANALYTICS_UPSERT_KEYS.get(table)
        if upsert_keys:
            # Preserve caller order so duplicate identities inside one delivery
            # deterministically keep the final payload without ever invoking
            # DuckDB's constraint-conflict and index rollback machinery.
            def _build_upsert_batch() -> pa.Table:
                return pa.Table.from_pylist(
                    [
                        {**{key: row.get(key) for key in columns}, "_analytics_order": index}
                        for index, row in enumerate(rows)
                    ],
                    schema=_arrow_schema(table).append(pa.field("_analytics_order", pa.uint64())),
                )

            batch = await asyncio.to_thread(_build_upsert_batch)
            partition = ", ".join(upsert_keys)
            source = (
                "(SELECT * EXCLUDE (_analytics_order, _analytics_rank) FROM ("
                "SELECT *, row_number() OVER (PARTITION BY "
                f"{partition} ORDER BY _analytics_order DESC) AS _analytics_rank FROM _analytics_batch"
                ") WHERE _analytics_rank = 1)"
            )
        else:

            def _build_append_batch() -> pa.Table:
                return pa.Table.from_pylist(
                    [{key: row.get(key) for key in columns} for row in rows],
                    schema=_arrow_schema(table),
                )

            batch = await asyncio.to_thread(_build_append_batch)
            source = "_analytics_batch"
        async with self._write_lock:
            con = self._require_writer()

            def _load() -> int:
                con.register("_analytics_batch", batch)
                try:
                    con.execute("BEGIN TRANSACTION")
                    if upsert_keys:
                        matches = " AND ".join(f"incoming.{key} = {table}.{key}" for key in upsert_keys)
                        con.execute(
                            f"DELETE FROM {table} WHERE EXISTS (SELECT 1 FROM {source} AS incoming WHERE {matches})"
                        )
                    con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM {source}")
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
                finally:
                    con.unregister("_analytics_batch")
                return len(rows)

            return await self._guard(con, _load)

    async def refresh_session_summary(self, project_id: str, user_id: str, harness: str, session_id: str) -> None:
        """Atomically recompute one session summary from canonical events."""
        params = {"pid": project_id, "uid": user_id, "harness": harness, "sid": session_id}
        async with self._write_lock:
            con = self._require_writer()

            def _refresh() -> None:
                con.execute("BEGIN TRANSACTION")
                try:
                    con.execute(
                        "DELETE FROM session_stats_agg WHERE project_id = $pid AND user_id = $uid "
                        "AND harness = $harness AND session_id = $sid",
                        params,
                    )
                    con.execute(
                        """
                        INSERT INTO session_stats_agg
                        SELECT
                            project_id,
                            session_id,
                            coalesce(max(agent_id) FILTER (WHERE agent_id IS NOT NULL AND agent_id != ''), ''),
                            coalesce(max(agent_version) FILTER (
                                WHERE agent_version IS NOT NULL AND agent_version != ''
                            ), ''),
                            user_id,
                            coalesce(max(parent_session_id) FILTER (WHERE parent_session_id IS NOT NULL), ''),
                            harness,
                            coalesce(max(layer_hash) FILTER (WHERE layer_hash IS NOT NULL AND layer_hash != ''), ''),
                            min(timestamp) FILTER (
                                WHERE rendered = 1 AND timestamp > TIMESTAMP '1971-01-01 00:00:00'
                                AND timestamp < TIMESTAMP '2099-01-01 00:00:00'
                            ),
                            max(timestamp) FILTER (
                                WHERE rendered = 1 AND timestamp > TIMESTAMP '1971-01-01 00:00:00'
                                AND timestamp < TIMESTAMP '2099-01-01 00:00:00'
                            ),
                            count(*) FILTER (WHERE rendered = 1),
                            count(*) FILTER (WHERE rendered = 1 AND event_type = 'user_prompt'),
                            count(*) FILTER (WHERE rendered = 1 AND event_type = 'tool_call'),
                            count(*) FILTER (WHERE rendered = 1 AND event_type = 'tool_result'),
                            coalesce(sum(input_tokens) FILTER (WHERE rendered = 1), 0),
                            coalesce(sum(output_tokens) FILTER (WHERE rendered = 1), 0),
                            coalesce(sum(cache_read_tokens) FILTER (WHERE rendered = 1), 0),
                            coalesce(sum(cache_write_tokens) FILTER (WHERE rendered = 1), 0),
                            coalesce(max(credits), 0),
                            coalesce(max(model) FILTER (WHERE rendered = 1 AND model != ''), ''),
                            CAST(epoch_ms(now()) AS UBIGINT),
                            now()
                        FROM session_events
                        WHERE project_id = $pid AND user_id = $uid AND harness = $harness AND session_id = $sid
                        GROUP BY project_id, session_id, user_id, harness
                        """,
                        params,
                    )
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise

            await self._guard(con, _refresh)

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
        column_list = ", ".join(columns)
        # Declaring the schema makes DuckDB return every target column, with
        # NULLs for columns the exported Parquet files do not carry (DuckDB
        # exports only the columns that existed at export time).
        declared = ", ".join(
            f"'{column}': {{'name': '{column}', 'type': '{types[column]}', 'default_value': NULL}}"
            for column in columns
        )
        identity_keys = ANALYTICS_UPSERT_KEYS.get(table) if replace else None
        dedupe_keys = identity_keys or ANALYTICS_DEDUPE_KEYS.get(table)
        async with self._write_lock:
            con = self._require_writer()

            def _load() -> int:
                before = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                # Import one partition per transaction. This bounds transaction
                # memory, makes retries resumable, and keeps append-only table
                # deduplication atomic with its corresponding insert.
                for path in paths:
                    escaped_path = "'" + str(path).replace("'", "''") + "'"
                    raw_source = f"read_parquet([{escaped_path}], schema = MAP {{{declared}}})"
                    if dedupe_keys:
                        partition = ", ".join(dedupe_keys)
                        source = (
                            f"(SELECT {column_list} FROM {raw_source} "
                            f"QUALIFY row_number() OVER (PARTITION BY {partition}) = 1)"
                        )
                    else:
                        source = raw_source
                    con.execute("BEGIN TRANSACTION")
                    try:
                        if dedupe_keys:
                            matches = " AND ".join(f"incoming.{key} = {table}.{key}" for key in dedupe_keys)
                            con.execute(
                                f"DELETE FROM {table} WHERE EXISTS (SELECT 1 FROM {source} AS incoming WHERE {matches})"
                            )
                        con.execute(f"INSERT INTO {table} ({column_list}) SELECT {column_list} FROM {source}")
                        con.execute("COMMIT")
                    except Exception:
                        con.execute("ROLLBACK")
                        raise
                after = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                return int(after - before)

            # Administrative bulk loads can legitimately exceed the ordinary
            # interactive query timeout. Process shutdown/cancellation remains
            # the outer operational bound.
            return await self._guard(con, _load, enforce_timeout=False)

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
        enforce_timeout: bool = True,
    ) -> tuple[list[str], list[tuple]]:
        def _work() -> tuple[list[str], list[tuple]]:
            result = con.execute(sql, params) if params else con.execute(sql)
            if not fetch:
                # DuckDB reports the affected-row count as a one-column result
                # set for DML, which is what the /execute contract returns.
                if _statement_verb(sql) in _DML_VERBS and result.description:
                    affected = result.fetchall()
                    count = int(affected[0][0]) if affected and affected[0] and affected[0][0] is not None else 0
                    return [], [(count,)]
                return [], []
            columns = [desc[0] for desc in (result.description or [])]
            rows = result.fetchmany(self.max_result_rows + 1)
            if len(rows) > self.max_result_rows:
                raise ValueError(
                    f"analytics result exceeds the {self.max_result_rows}-row response limit; paginate the query"
                )
            return columns, [_jsonable_row(row) for row in rows]

        return await self._guard(con, _work, enforce_timeout=enforce_timeout)

    async def _guard(
        self,
        con: duckdb.DuckDBPyConnection,
        work: Callable[[], object],
        *,
        enforce_timeout: bool = True,
    ):
        task = asyncio.create_task(asyncio.to_thread(work))
        try:
            if not enforce_timeout:
                return await asyncio.shield(task)
            return await asyncio.wait_for(asyncio.shield(task), timeout=self.query_timeout)
        except (TimeoutError, asyncio.CancelledError) as exc:
            # A cancelled to_thread awaitable does not stop its worker thread.
            # Interrupt it and wait for the thread to leave DuckDB before the
            # caller can return this connection to the reader pool (or release
            # the writer lock). Reusing a still-busy connection can corrupt the
            # next query with a delayed interrupt.
            optic.warning(
                "DuckDB query interrupted{}",
                f" after {self.query_timeout}s" if isinstance(exc, TimeoutError) else " by cancellation",
            )
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

        Each table is scanned exactly once. DuckDB's partitioned COPY writes one
        file per month in a single pass; filtering the table once per month
        instead re-reads the whole table for every month of history. The
        partition value also lands inside the file as ``_analytics_month`` -
        the loaders select the table's declared columns, so the extra column is
        ignored on import.
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
            table_match = _SAFE_PATH_COMPONENT.fullmatch(table) if isinstance(table, str) else None
            if columns is None or time_column is None or table_match is None:
                continue
            # Rebuilt from the validated pattern instead of reusing the caller's
            # string, so the name that reaches the filesystem is never raw input.
            table_name = table_match.group(0)
            async with self._write_lock:
                con = self._require_writer()

                def _export(
                    connection: duckdb.DuckDBPyConnection = con,
                    table_name: str = table_name,
                    time_col: str = time_column,
                    destination: Path = target,
                ) -> int:
                    parts = destination / f".{table_name}.parts"
                    parts.mkdir(parents=True, exist_ok=True)
                    escaped_parts = str(parts).replace("'", "''")
                    try:
                        connection.execute(
                            f"COPY (SELECT *, strftime(CAST({time_col} AS DATE), '%Y-%m') AS _analytics_month "
                            f"FROM {table_name}) "
                            f"TO '{escaped_parts}' (FORMAT PARQUET, PARTITION_BY (_analytics_month))"
                        )
                        total = 0
                        for partition in sorted(parts.iterdir()):
                            if not partition.is_dir():
                                continue
                            # DuckDB names partitions "<column>=<value>" and writes
                            # the NULL bucket as __HIVE_DEFAULT_PARTITION__, which
                            # becomes the exporter's "<table>_null.parquet".
                            value = partition.name.split("=", 1)[-1]
                            month_match = _SAFE_MONTH.fullmatch(value)
                            month = month_match.group(0) if month_match else "null"
                            target_file = destination / f"{table_name}_{month}.parquet"
                            if target_file.resolve().parent != target.resolve():
                                continue
                            chunks = sorted(partition.glob("*.parquet"))
                            if not chunks:
                                continue
                            if len(chunks) == 1:
                                chunks[0].replace(target_file)
                            else:
                                # A partition DuckDB flushed more than once still
                                # has to arrive as one file per month.
                                escaped_chunks = ", ".join(
                                    "'" + str(chunk).replace("'", "''") + "'" for chunk in chunks
                                )
                                escaped_target = str(target_file).replace("'", "''")
                                connection.execute(
                                    f"COPY (SELECT * FROM read_parquet([{escaped_chunks}])) "
                                    f"TO '{escaped_target}' (FORMAT PARQUET)"
                                )
                            escaped_target = str(target_file).replace("'", "''")
                            total += int(
                                connection.execute(f"SELECT count(*) FROM read_parquet('{escaped_target}')").fetchone()[
                                    0
                                ]
                                or 0
                            )
                        return total
                    finally:
                        shutil.rmtree(parts, ignore_errors=True)

                # Instance moves and backups legitimately exceed the interactive
                # query deadline on multi-million-row tables; only process
                # shutdown bounds an administrative export.
                counts[table] = await self._guard(con, _export, enforce_timeout=False)
        return counts
