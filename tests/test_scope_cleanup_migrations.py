# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Structural smoke checks for the hard deployment-scope cleanup."""

import importlib.util
from pathlib import Path

from models import Base

ROOT = Path(__file__).resolve().parents[1]


def _load_postgres_cleanup():
    path = ROOT / "observal-server" / "alembic" / "versions" / "020_remove_legacy_scope.py"
    spec = importlib.util.spec_from_file_location("scope_cleanup", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fresh_models_include_deployment_settings_and_team_ownership():
    table_names = set(Base.metadata.tables)
    column_names = {column.name for table in Base.metadata.tables.values() for column in table.columns}
    assert {"enterprise_config", "teams", "team_memberships"} <= table_names
    assert {"team_id", "role"} <= column_names


def test_postgres_cleanup_is_the_next_alembic_revision():
    migration = _load_postgres_cleanup()
    assert migration.revision == "020_remove_legacy_scope"
    assert migration.down_revision == "019_team_listing_restrict"
    assert "security.trace_privacy" in migration._COPY_SETTINGS
    assert "registry.registered_agents_only" in migration._COPY_SETTINGS
    assert "retention.trace_days" in migration._COPY_SETTINGS
    assert "gen_random_uuid()" in migration._COPY_SETTINGS
    assert "updated_at" in migration._COPY_SETTINGS
    assert callable(migration.upgrade)


def test_clickhouse_cleanup_stages_and_validates_keyed_tables():
    path = ROOT / "observal-server" / "clickhouse" / "migrations" / "004_remove_legacy_scope.sql"
    sql = path.read_text()
    assert "session_events_scope_cleanup" in sql
    assert "session_checkpoints_scope_cleanup" in sql
    assert "session_stats_agg_scope_cleanup" in sql
    assert "layer_snapshots_scope_cleanup" in sql
    assert sql.count("throwIf") >= 6
    assert "'default'" in sql
    assert sql.count("DROP COLUMN IF EXISTS") >= 2
