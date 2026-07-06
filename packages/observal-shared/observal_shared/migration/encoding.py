# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""JSON encoding and SQL builders for PostgreSQL migration data."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from observal_shared.migration.constants import INSERT_ORDER, JSONB_COLUMNS


class PGEncoder(json.JSONEncoder):
    """Custom JSON encoder for PostgreSQL row data."""

    def default(self, obj: object) -> object:
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, timedelta):
            return obj.total_seconds()
        return super().default(obj)


def _coerce_value(value: object, pg_type: str) -> object:
    """Coerce a JSON-deserialized value to the correct Python type for asyncpg."""
    if value is None:
        return None
    if pg_type == "uuid" and isinstance(value, str):
        return uuid.UUID(value)
    if pg_type in ("timestamptz", "timestamp") and isinstance(value, str):
        return datetime.fromisoformat(value)
    if pg_type == "interval" and isinstance(value, (int, float)):
        return timedelta(seconds=value)
    if pg_type in ("bool",):
        if isinstance(value, bool):
            return value
        elif isinstance(value, str):
            # Handle string defaults from column_default ('true', 'false')
            return value.lower() in ("true", "t", "1", "yes")
    if pg_type in ("int4", "int8", "int2") and isinstance(value, (int, float)):
        return int(value)
    if pg_type in ("float4", "float8", "numeric") and isinstance(value, (int, float)):
        return float(value)
    # asyncpg requires JSON/JSONB values as serialized strings
    if pg_type in ("json", "jsonb") and not isinstance(value, str):
        return json.dumps(value)
    return value


def _build_select(table: str, columns: list[str]) -> str:
    """Build SELECT query, casting JSONB columns to ::text.

    Table names are validated against INSERT_ORDER as a defense-in-depth
    assertion - callers always pass values from INSERT_ORDER, but this
    guards against accidental misuse by future callers passing unknown tables.
    """
    if table not in INSERT_ORDER:
        msg = f"Unknown table: {table!r}"
        raise ValueError(msg)
    jsonb_cols = JSONB_COLUMNS.get(table, [])
    if not jsonb_cols:
        return f'SELECT * FROM "{table}"'
    parts = []
    for col in columns:
        if col in jsonb_cols:
            parts.append(f'"{col}"::text AS "{col}"')
        else:
            parts.append(f'"{col}"')
    return f'SELECT {", ".join(parts)} FROM "{table}"'


def _build_insert(table: str, columns: list[str], col_types: dict[str, str]) -> str:
    """Build INSERT query with proper type casts for JSONB columns."""
    cols_str = ", ".join(f'"{col}"' for col in columns)
    parts = []
    for i, col in enumerate(columns):
        pg_type = col_types.get(col, "")
        if pg_type in ("json", "jsonb"):
            parts.append(f"${i + 1}::jsonb")
        else:
            parts.append(f"${i + 1}")
    placeholders = ", ".join(parts)
    return f'INSERT INTO "{table}" ({cols_str}) VALUES ({placeholders}) ON CONFLICT ("id") DO NOTHING'
