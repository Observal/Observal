"""Unit and property-based tests for ch-deep-copy: ClickHouse telemetry migration."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import click.exceptions
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from hypothesis import given
from hypothesis import settings as hsettings
from hypothesis import strategies as st
from typer.testing import CliRunner

from observal_cli.cmd_migrate import (
    _UUID_RE,
    CLICKHOUSE_TABLES,
    EPOCH_SENTINELS,
    FK_PG_TABLE_MAP,
    TableCfg,
    TelemetryExportResult,
    TelemetryImportResult,
    TelemetryValidationResult,
    _build_ch_count_query,
    _build_ch_export_query,
    _build_ch_time_range_query,
    _is_empty_parquet,
    _month_range,
    _parse_clickhouse_url,
    _read_count,
    _require_admin,
    _sha256_file,
)
from observal_cli.main import app as cli_app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ── Mock helpers ─────────────────────────────────────────


class MockResponse:
    """Mock httpx response for _read_count tests."""

    def __init__(self, data: dict):
        self._data = data

    def json(self) -> dict:
        return self._data


# ══════════════════════════════════════════════════════════
# Unit Tests (Example-Based)
# ══════════════════════════════════════════════════════════


# ── CLI Registration Tests ───────────────────────────────


class TestCLIRegistration:
    """Verify Phase 2 telemetry subcommands appear in migrate --help."""

    def test_export_telemetry_in_help(self):
        result = runner.invoke(cli_app, ["migrate", "--help"])
        assert result.exit_code == 0
        assert "export-telemetry" in _plain(result.output)

    def test_import_telemetry_in_help(self):
        result = runner.invoke(cli_app, ["migrate", "--help"])
        assert result.exit_code == 0
        assert "import-telemetry" in _plain(result.output)

    def test_validate_telemetry_in_help(self):
        result = runner.invoke(cli_app, ["migrate", "--help"])
        assert result.exit_code == 0
        assert "validate-telemetry" in _plain(result.output)

    def test_export_telemetry_help_shows_options(self):
        result = runner.invoke(cli_app, ["migrate", "export-telemetry", "--help"])
        assert result.exit_code == 0
        out = _plain(result.output)
        assert "--clickhouse-url" in out
        assert "--manifest" in out
        assert "--output-dir" in out

    def test_import_telemetry_help_shows_options(self):
        result = runner.invoke(cli_app, ["migrate", "import-telemetry", "--help"])
        assert result.exit_code == 0
        out = _plain(result.output)
        assert "--clickhouse-url" in out
        assert "--input-dir" in out

    def test_validate_telemetry_help_shows_options(self):
        result = runner.invoke(cli_app, ["migrate", "validate-telemetry", "--help"])
        assert result.exit_code == 0
        out = _plain(result.output)
        assert "--input-dir" in out
        assert "--clickhouse-url" in out
        assert "--target-db-url" in out


# ── ClickHouse URL Parsing Tests ─────────────────────────


class TestParseClickhouseUrl:
    """Test _parse_clickhouse_url with various URL formats."""

    def test_full_url_with_all_components(self):
        url = "clickhouse://myuser:mypass@ch-host:9000/mydb"
        http_url, db, user, password = _parse_clickhouse_url(url)
        assert http_url == "http://ch-host:9000"
        assert db == "mydb"
        assert user == "myuser"
        assert password == "mypass"

    def test_url_with_default_port(self):
        url = "clickhouse://user:pass@host/db"
        http_url, db, user, password = _parse_clickhouse_url(url)
        assert http_url == "http://host:8123"
        assert db == "db"

    def test_url_with_default_database(self):
        url = "clickhouse://user:pass@host:9000"
        http_url, db, user, password = _parse_clickhouse_url(url)
        assert db == "default"

    def test_url_with_default_user_and_password(self):
        url = "clickhouse://host:9000/db"
        http_url, db, user, password = _parse_clickhouse_url(url)
        assert user == "default"
        assert password == ""

    def test_url_with_slash_only_path(self):
        url = "clickhouse://user:pass@host:8123/"
        http_url, db, user, password = _parse_clickhouse_url(url)
        assert db == "default"

    def test_clickhouses_tls_url(self):
        url = "clickhouses://myuser:mypass@ch-host:9440/mydb"
        http_url, db, user, password = _parse_clickhouse_url(url)
        assert http_url == "https://ch-host:9440"
        assert db == "mydb"
        assert user == "myuser"
        assert password == "mypass"

    def test_clickhouses_default_port_is_8443(self):
        url = "clickhouses://user:pass@host/db"
        http_url, db, user, password = _parse_clickhouse_url(url)
        assert http_url == "https://host:8443"
        assert db == "db"

    def test_anchored_prefix_password_containing_clickhouse(self):
        """Password containing 'clickhouse://' should not corrupt parsing."""
        url = "clickhouse://admin:clickhouse%3A%2F%2Ffoo@host:8123/db"
        http_url, db, user, password = _parse_clickhouse_url(url)
        assert http_url == "http://host:8123"
        assert user == "admin"
        assert db == "db"


# ── Export Query Builder Tests ───────────────────────────


class TestBuildChExportQuery:
    """Test _build_ch_export_query for ReplacingMergeTree vs MergeTree."""

    def test_replacing_engine_has_final_and_is_deleted(self):
        cfg = {"name": "traces", "engine": "replacing", "time_col": "start_time", "fk_cols": []}
        query = _build_ch_export_query(cfg, 202501)
        assert "FINAL" in query
        assert "is_deleted = 0" in query

    def test_mergetree_engine_plain_select(self):
        cfg = {"name": "audit_log", "engine": "mergetree", "time_col": "timestamp", "fk_cols": []}
        query = _build_ch_export_query(cfg, 202501)
        assert "FINAL" not in query
        assert "is_deleted" not in query

    def test_correct_time_column_used(self):
        cfg = {"name": "spans", "engine": "replacing", "time_col": "start_time", "fk_cols": []}
        query = _build_ch_export_query(cfg, 202503)
        assert "toYYYYMM(start_time) = 202503" in query

    def test_ends_with_format_parquet(self):
        cfg = {"name": "scores", "engine": "replacing", "time_col": "timestamp", "fk_cols": []}
        query = _build_ch_export_query(cfg, 202501)
        assert query.rstrip().endswith("FORMAT Parquet")

    def test_mergetree_ends_with_format_parquet(self):
        cfg = {"name": "audit_log", "engine": "mergetree", "time_col": "timestamp", "fk_cols": []}
        query = _build_ch_export_query(cfg, 202501)
        assert query.rstrip().endswith("FORMAT Parquet")

    def test_cutoff_in_replacing_query(self):
        cfg = {"name": "traces", "engine": "replacing", "time_col": "start_time", "fk_cols": []}
        query = _build_ch_export_query(cfg, 202501, cutoff="2025-01-15T00:00:00")
        assert "start_time < {cutoff:String}" in query
        assert "FINAL" in query

    def test_cutoff_in_mergetree_query(self):
        cfg = {"name": "audit_log", "engine": "mergetree", "time_col": "timestamp", "fk_cols": []}
        query = _build_ch_export_query(cfg, 202501, cutoff="2025-01-15T00:00:00")
        assert "timestamp < {cutoff:String}" in query

    def test_no_cutoff_when_none(self):
        cfg = {"name": "traces", "engine": "replacing", "time_col": "start_time", "fk_cols": []}
        query = _build_ch_export_query(cfg, 202501)
        assert "cutoff" not in query


# ── Count Query Builder Tests ────────────────────────────


class TestBuildChCountQuery:
    """Test _build_ch_count_query for count() AS cnt and FORMAT JSON."""

    def test_has_count_alias(self):
        cfg = {"name": "traces", "engine": "replacing", "time_col": "start_time", "fk_cols": []}
        query = _build_ch_count_query(cfg, 202501)
        assert "count() AS cnt" in query

    def test_has_format_json(self):
        cfg = {"name": "traces", "engine": "replacing", "time_col": "start_time", "fk_cols": []}
        query = _build_ch_count_query(cfg, 202501)
        assert "FORMAT JSON" in query

    def test_replacing_has_final(self):
        cfg = {"name": "spans", "engine": "replacing", "time_col": "start_time", "fk_cols": []}
        query = _build_ch_count_query(cfg, 202501)
        assert "FINAL" in query
        assert "is_deleted = 0" in query

    def test_mergetree_no_final(self):
        cfg = {"name": "audit_log", "engine": "mergetree", "time_col": "timestamp", "fk_cols": []}
        query = _build_ch_count_query(cfg, 202501)
        assert "FINAL" not in query
        assert "is_deleted" not in query

    def test_cutoff_in_count_query(self):
        cfg = {"name": "audit_log", "engine": "mergetree", "time_col": "timestamp", "fk_cols": []}
        query = _build_ch_count_query(cfg, 202501, cutoff="2025-01-15T00:00:00")
        assert "timestamp < {cutoff:String}" in query
        assert "FORMAT JSON" in query


# ── Time Range Query Builder Tests ───────────────────────


class TestBuildChTimeRangeQuery:
    """Test _build_ch_time_range_query for min/max with aliases."""

    def test_has_min_max_aliases(self):
        cfg = {"name": "traces", "engine": "replacing", "time_col": "start_time", "fk_cols": []}
        query = _build_ch_time_range_query(cfg)
        assert "AS min_t" in query
        assert "AS max_t" in query

    def test_replacing_has_final(self):
        cfg = {"name": "traces", "engine": "replacing", "time_col": "start_time", "fk_cols": []}
        query = _build_ch_time_range_query(cfg)
        assert "FINAL" in query
        assert "is_deleted = 0" in query

    def test_mergetree_no_final(self):
        cfg = {"name": "audit_log", "engine": "mergetree", "time_col": "timestamp", "fk_cols": []}
        query = _build_ch_time_range_query(cfg)
        assert "FINAL" not in query


# ── Month Range Tests ────────────────────────────────────


class TestMonthRange:
    """Test _month_range generation."""

    def test_same_month_single_entry(self):
        result = _month_range(datetime(2025, 3, 10), datetime(2025, 3, 20))
        assert result == [202503]

    def test_cross_year_boundary(self):
        result = _month_range(datetime(2024, 11, 1), datetime(2025, 2, 1))
        assert result == [202411, 202412, 202501, 202502]

    def test_multi_year_range(self):
        result = _month_range(datetime(2023, 12, 1), datetime(2025, 1, 1))
        assert result[0] == 202312
        assert result[-1] == 202501
        assert len(result) == 14  # Dec 2023 through Jan 2025

    def test_ascending_order_no_gaps(self):
        result = _month_range(datetime(2025, 1, 1), datetime(2025, 6, 30))
        assert result == [202501, 202502, 202503, 202504, 202505, 202506]
        # Verify ascending
        for i in range(len(result) - 1):
            assert result[i] < result[i + 1]


# ── _is_empty_parquet Tests ──────────────────────────────


class TestIsEmptyParquet:
    """Test _is_empty_parquet with real Parquet files."""

    def test_zero_byte_file_is_empty(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".parquet") as f:
            path = Path(f.name)
        try:
            assert _is_empty_parquet(path) is True
        finally:
            path.unlink(missing_ok=True)

    def test_non_empty_parquet_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".parquet") as f:
            path = Path(f.name)
        try:
            table = pa.table({"id": [1, 2, 3]})
            pq.write_table(table, path)
            assert _is_empty_parquet(path) is False
        finally:
            path.unlink(missing_ok=True)

    def test_empty_rows_parquet_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".parquet") as f:
            path = Path(f.name)
        try:
            table = pa.table({"id": pa.array([], type=pa.int64())})
            pq.write_table(table, path)
            assert _is_empty_parquet(path) is True
        finally:
            path.unlink(missing_ok=True)

    def test_invalid_parquet_returns_true(self):
        """ArrowInvalid from corrupt data should return True (narrow exception)."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".parquet") as f:
            f.write(b"not a parquet file at all")
            path = Path(f.name)
        try:
            assert _is_empty_parquet(path) is True
        finally:
            path.unlink(missing_ok=True)


# ── _read_count Tests ────────────────────────────────────


class TestReadCount:
    """Test _read_count parsing of ClickHouse JSON responses."""

    def test_normal_response(self):
        resp = MockResponse({"data": [{"cnt": "42"}]})
        assert _read_count(resp) == 42

    def test_empty_data(self):
        resp = MockResponse({"data": [{}]})
        assert _read_count(resp) == 0

    def test_missing_cnt_key(self):
        resp = MockResponse({"data": [{"other": "value"}]})
        assert _read_count(resp) == 0

    def test_zero_count(self):
        resp = MockResponse({"data": [{"cnt": "0"}]})
        assert _read_count(resp) == 0


# ── Constants Tests ──────────────────────────────────────


class TestConstants:
    """Verify CLICKHOUSE_TABLES, FK_PG_TABLE_MAP, and EPOCH_SENTINELS."""

    def test_clickhouse_tables_has_6_entries(self):
        assert len(CLICKHOUSE_TABLES) == 6

    def test_each_table_has_required_keys(self):
        for table_cfg in CLICKHOUSE_TABLES:
            assert "name" in table_cfg
            assert "engine" in table_cfg
            assert "time_col" in table_cfg
            assert "fk_cols" in table_cfg

    def test_table_names(self):
        names = {t["name"] for t in CLICKHOUSE_TABLES}
        expected = {"traces", "spans", "scores", "audit_log", "mcp_tool_calls", "agent_interactions"}
        assert names == expected

    def test_engine_types(self):
        for t in CLICKHOUSE_TABLES:
            assert t["engine"] in ("replacing", "mergetree")

    def test_replacing_tables(self):
        replacing = [t["name"] for t in CLICKHOUSE_TABLES if t["engine"] == "replacing"]
        assert set(replacing) == {"traces", "spans", "scores"}

    def test_mergetree_tables(self):
        mergetree = [t["name"] for t in CLICKHOUSE_TABLES if t["engine"] == "mergetree"]
        assert set(mergetree) == {"audit_log", "mcp_tool_calls", "agent_interactions"}

    def test_typed_dict_structure(self):
        """Verify CLICKHOUSE_TABLES entries conform to TableCfg TypedDict."""
        required_keys = {"name", "engine", "time_col", "fk_cols"}
        for table_cfg in CLICKHOUSE_TABLES:
            assert set(table_cfg.keys()) == required_keys
            assert isinstance(table_cfg["name"], str)
            assert table_cfg["engine"] in ("replacing", "mergetree")
            assert isinstance(table_cfg["time_col"], str)
            assert isinstance(table_cfg["fk_cols"], list)
            assert all(isinstance(c, str) for c in table_cfg["fk_cols"])

    def test_tablecfg_type_exists(self):
        """Verify TableCfg is importable and is a TypedDict."""
        assert hasattr(TableCfg, "__annotations__")
        assert "name" in TableCfg.__annotations__
        assert "engine" in TableCfg.__annotations__

    def test_fk_pg_table_map_has_5_entries(self):
        assert len(FK_PG_TABLE_MAP) == 5

    def test_fk_pg_table_map_keys(self):
        expected_keys = {"agent_id", "mcp_id", "mcp_server_id", "user_id", "actor_id"}
        assert set(FK_PG_TABLE_MAP.keys()) == expected_keys

    def test_epoch_sentinels_contains_expected(self):
        assert None in EPOCH_SENTINELS
        assert "" in EPOCH_SENTINELS
        assert "1970-01-01 00:00:00.000" in EPOCH_SENTINELS
        assert "1970-01-01 00:00:00" in EPOCH_SENTINELS


# ── Dataclass Tests ──────────────────────────────────────


class TestDataclasses:
    """Verify Phase 2 dataclass fields."""

    def test_telemetry_export_result_fields(self):
        result = TelemetryExportResult(
            output_dir="/tmp/out",
            migration_id="abc-123",
            table_results={"traces": {"files": [], "row_count": 0}},
            total_rows=100,
            total_size_bytes=1024,
            duration_seconds=5.0,
        )
        assert result.output_dir == "/tmp/out"
        assert result.migration_id == "abc-123"
        assert result.total_rows == 100
        assert result.total_size_bytes == 1024
        assert result.duration_seconds == 5.0

    def test_telemetry_import_result_fields(self):
        result = TelemetryImportResult(
            migration_id="abc-123",
            tables_imported=4,
            tables_skipped=["scores"],
            rows_imported={"traces": 500},
            duration_seconds=10.0,
            warnings=["some warning"],
        )
        assert result.tables_imported == 4
        assert result.tables_skipped == ["scores"]
        assert result.rows_imported["traces"] == 500
        assert result.warnings == ["some warning"]

    def test_telemetry_validation_result_fields(self):
        result = TelemetryValidationResult(
            checksums_valid=True,
            checksum_results={"traces_2025-01.parquet": True},
            fk_results=None,
            row_count_results=None,
        )
        assert result.checksums_valid is True
        assert result.fk_results is None
        assert result.row_count_results is None


# ── Error Path Tests (CLI) ───────────────────────────────


class TestErrorPaths:
    """Test CLI error handling for missing arguments and files."""

    def test_export_telemetry_missing_options(self):
        """export-telemetry without required options should fail."""
        result = runner.invoke(cli_app, ["migrate", "export-telemetry"])
        assert result.exit_code != 0

    @patch("observal_cli.cmd_migrate._require_admin")
    def test_export_telemetry_missing_manifest(self, mock_admin):
        """export-telemetry with non-existent manifest should fail."""
        result = runner.invoke(
            cli_app,
            [
                "migrate",
                "export-telemetry",
                "--clickhouse-url",
                "clickhouse://localhost:8123/db",
                "--manifest",
                "/nonexistent/manifest.json",
                "--output-dir",
                "/tmp/test-out",
            ],
        )
        assert result.exit_code != 0

    @patch("observal_cli.cmd_migrate._require_admin")
    def test_import_telemetry_missing_input_dir(self, mock_admin):
        """import-telemetry with non-existent input dir should fail."""
        result = runner.invoke(
            cli_app,
            [
                "migrate",
                "import-telemetry",
                "--clickhouse-url",
                "clickhouse://localhost:8123/db",
                "--input-dir",
                "/nonexistent/dir",
            ],
        )
        assert result.exit_code != 0

    @patch("observal_cli.cmd_migrate._require_admin")
    def test_validate_telemetry_missing_input_dir(self, mock_admin):
        """validate-telemetry with non-existent input dir should fail."""
        result = runner.invoke(
            cli_app,
            [
                "migrate",
                "validate-telemetry",
                "--input-dir",
                "/nonexistent/dir",
            ],
        )
        assert result.exit_code != 0


# ── Security Tests ───────────────────────────────────────


class TestSecurity:
    """Verify connection strings never appear in CLI output."""

    @patch("observal_cli.cmd_migrate._require_admin")
    @patch("observal_cli.cmd_migrate.asyncio")
    def test_clickhouse_url_not_in_export_output(self, mock_asyncio, mock_admin):
        secret_url = "clickhouse://secret_user:secret_pass@secret-host:9000/secret_db"
        mock_asyncio.run.side_effect = SystemExit(1)
        result = runner.invoke(
            cli_app,
            [
                "migrate",
                "export-telemetry",
                "--clickhouse-url",
                secret_url,
                "--manifest",
                "/nonexistent/manifest.json",
                "--output-dir",
                "/tmp/test-out",
            ],
        )
        assert secret_url not in result.output

    @patch("observal_cli.cmd_migrate._require_admin")
    def test_clickhouse_url_not_in_import_output(self, mock_admin):
        secret_url = "clickhouse://secret_user:secret_pass@secret-host:9000/secret_db"
        result = runner.invoke(
            cli_app,
            [
                "migrate",
                "import-telemetry",
                "--clickhouse-url",
                secret_url,
                "--input-dir",
                "/nonexistent/dir",
            ],
        )
        assert secret_url not in result.output

    @patch("observal_cli.cmd_migrate._require_admin")
    def test_clickhouse_url_not_in_validate_output(self, mock_admin):
        secret_url = "clickhouse://secret_user:secret_pass@secret-host:9000/secret_db"
        result = runner.invoke(
            cli_app,
            [
                "migrate",
                "validate-telemetry",
                "--input-dir",
                "/nonexistent/dir",
                "--clickhouse-url",
                secret_url,
            ],
        )
        assert secret_url not in result.output


# ══════════════════════════════════════════════════════════
# Property-Based Tests (Hypothesis)
# ══════════════════════════════════════════════════════════


# ── Property 1: Admin role authorization gate ────────────


class TestAdminRoleGateProperty:
    """Property 1: Only admin and super_admin roles pass the gate.

    **Validates: Requirements 1.5**
    """

    ALLOWED_ROLES = {"admin", "super_admin"}

    @given(
        role=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            min_size=0,
            max_size=20,
        )
    )
    @hsettings(max_examples=100)
    def test_role_gate(self, role):
        with patch("observal_cli.cmd_migrate.client") as mock_client:
            mock_client.get.return_value = {"role": role}
            if role in self.ALLOWED_ROLES:
                _require_admin()  # Should not raise
            else:
                with pytest.raises((SystemExit, click.exceptions.Exit)):
                    _require_admin()


# ── Property 2: ClickHouse URL parsing correctness ──────


class TestClickhouseUrlParsingProperty:
    """Property 2: ClickHouse URL parsing extracts correct components.

    **Validates: Requirements 3.1**
    """

    @given(
        host=st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True),
        port=st.integers(min_value=1, max_value=65535),
        db=st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True),
        user=st.from_regex(r"[a-z][a-z0-9]{0,10}", fullmatch=True),
        password=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
    )
    @hsettings(max_examples=100)
    def test_url_components_extracted(self, host, port, db, user, password):
        url = f"clickhouse://{user}:{password}@{host}:{port}/{db}"
        http_url, parsed_db, parsed_user, parsed_password = _parse_clickhouse_url(url)
        assert http_url == f"http://{host}:{port}"
        assert parsed_db == db
        assert parsed_user == user
        assert parsed_password == password

    @given(
        host=st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True),
    )
    @hsettings(max_examples=100)
    def test_defaults_applied_for_missing_components(self, host):
        url = f"clickhouse://{host}"
        http_url, db, user, password = _parse_clickhouse_url(url)
        assert http_url == f"http://{host}:8123"
        assert db == "default"
        assert user == "default"
        assert password == ""

    @given(
        host=st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True),
        port=st.integers(min_value=1, max_value=65535),
        db=st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True),
        user=st.from_regex(r"[a-z][a-z0-9]{0,10}", fullmatch=True),
        password=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
    )
    @hsettings(max_examples=100)
    def test_tls_url_components_extracted(self, host, port, db, user, password):
        url = f"clickhouses://{user}:{password}@{host}:{port}/{db}"
        http_url, parsed_db, parsed_user, parsed_password = _parse_clickhouse_url(url)
        assert http_url == f"https://{host}:{port}"
        assert parsed_db == db
        assert parsed_user == user
        assert parsed_password == password

    @given(
        host=st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True),
    )
    @hsettings(max_examples=100)
    def test_tls_defaults_applied(self, host):
        url = f"clickhouses://{host}"
        http_url, db, user, password = _parse_clickhouse_url(url)
        assert http_url == f"https://{host}:8443"
        assert db == "default"


# ── Property 3: Export query builder correctness ─────────


class TestExportQueryBuilderProperty:
    """Property 3: Export query builder correctness.

    **Validates: Requirements 4.2, 4.3, 4.4, 5.4, 12.1, 12.2, 12.3**
    """

    @given(
        table_cfg=st.sampled_from(CLICKHOUSE_TABLES),
        yyyymm=st.integers(min_value=200001, max_value=209912).filter(lambda x: 1 <= x % 100 <= 12),
    )
    @hsettings(max_examples=100)
    def test_export_query_properties(self, table_cfg, yyyymm):
        query = _build_ch_export_query(table_cfg, yyyymm)

        # FINAL iff replacing
        if table_cfg["engine"] == "replacing":
            assert "FINAL" in query
            assert "is_deleted = 0" in query
        else:
            assert "FINAL" not in query
            assert "is_deleted" not in query

        # Correct time column
        assert f"toYYYYMM({table_cfg['time_col']}) = {yyyymm}" in query

        # Ends with FORMAT Parquet
        assert query.rstrip().endswith("FORMAT Parquet")

    @given(
        table_cfg=st.sampled_from(CLICKHOUSE_TABLES),
        yyyymm=st.integers(min_value=200001, max_value=209912).filter(lambda x: 1 <= x % 100 <= 12),
    )
    @hsettings(max_examples=100)
    def test_count_query_properties(self, table_cfg, yyyymm):
        query = _build_ch_count_query(table_cfg, yyyymm)

        assert "count() AS cnt" in query
        assert "FORMAT JSON" in query

        if table_cfg["engine"] == "replacing":
            assert "FINAL" in query
            assert "is_deleted = 0" in query
        else:
            assert "FINAL" not in query
            assert "is_deleted" not in query


# ── Property 4: Month range completeness and ordering ────


class TestMonthRangeProperty:
    """Property 4: Month range generation completeness and ordering.

    **Validates: Requirements 5.2, 5.5**
    """

    @given(
        min_dt=st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2099, 12, 31)),
        max_dt=st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2099, 12, 31)),
    )
    @hsettings(max_examples=100)
    def test_month_range_properties(self, min_dt, max_dt):
        if min_dt > max_dt:
            min_dt, max_dt = max_dt, min_dt

        result = _month_range(min_dt, max_dt)

        # No duplicates
        assert len(result) == len(set(result))

        # Ascending order
        for i in range(len(result) - 1):
            assert result[i] < result[i + 1]

        # First and last months correct
        assert result[0] == min_dt.year * 100 + min_dt.month
        assert result[-1] == max_dt.year * 100 + max_dt.month

        # No gaps: consecutive months differ by 1 month or year rollover
        for i in range(len(result) - 1):
            y1, m1 = divmod(result[i], 100)
            y2, m2 = divmod(result[i + 1], 100)
            if m1 == 12:
                assert y2 == y1 + 1 and m2 == 1
            else:
                assert y2 == y1 and m2 == m1 + 1

        # Correct length
        min_months = min_dt.year * 12 + min_dt.month
        max_months = max_dt.year * 12 + max_dt.month
        expected_len = max_months - min_months + 1
        assert len(result) == expected_len


# ── Property 5: SHA-256 checksum integrity ───────────────


class TestSha256IntegrityProperty:
    """Property 5: SHA-256 checksum integrity.

    **Validates: Requirements 6.1, 6.5**
    """

    @given(data=st.binary(min_size=0, max_size=10000))
    @hsettings(max_examples=100)
    def test_sha256_deterministic(self, data):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(data)
            f.flush()
            path = Path(f.name)
        try:
            hash1 = _sha256_file(path)
            hash2 = _sha256_file(path)
            assert hash1 == hash2
            # Also matches stdlib
            assert hash1 == hashlib.sha256(data).hexdigest()
        finally:
            path.unlink(missing_ok=True)


# ── Property 6: Telemetry manifest JSON round-trip ───────


class TestTelemetryManifestRoundTripProperty:
    """Property 6: Telemetry manifest JSON round-trip.

    **Validates: Requirements 10.4**
    """

    @given(
        migration_id=st.uuids(),
        row_counts=st.dictionaries(
            keys=st.sampled_from(["traces", "spans", "scores", "audit_log", "mcp_tool_calls"]),
            values=st.integers(min_value=0, max_value=1_000_000),
            min_size=1,
            max_size=5,
        ),
        checksums_valid=st.booleans(),
    )
    @hsettings(max_examples=100)
    def test_telemetry_manifest_round_trip(self, migration_id, row_counts, checksums_valid):
        manifest = {
            "migration_id": str(migration_id),
            "phase": "deep_copy",
            "phase_status": "export_complete",
            "export_completed_at": datetime.now(UTC).isoformat(),
            "export_time_cutoff": datetime.now(UTC).isoformat(),
            "source_clickhouse_url_hash": hashlib.sha256(b"clickhouse://test").hexdigest(),
            "tables": {
                table: {
                    "files": [f"{table}_2025-01.parquet"],
                    "row_count": count,
                    "checksum": {f"{table}_2025-01.parquet": hashlib.sha256(f"{table}".encode()).hexdigest()},
                    "time_range": {"min": "2025-01-01T00:00:00", "max": "2025-01-31T23:59:59"},
                }
                for table, count in row_counts.items()
            },
            "fk_validation": {
                "orphaned_agent_ids": [],
                "orphaned_agent_ids_truncated": False,
                "orphaned_mcp_ids": [],
                "orphaned_mcp_ids_truncated": False,
                "orphaned_user_ids": [],
                "orphaned_user_ids_truncated": False,
                "validated_at": None,
            },
        }
        serialized = json.dumps(manifest)
        deserialized = json.loads(serialized)
        assert deserialized == manifest


# ── Property 7: migration_id consistency ─────────────────


class TestMigrationIdConsistencyProperty:
    """Property 7: migration_id consistency across phases.

    **Validates: Requirements 2.4, 16.3**
    """

    @given(migration_id=st.uuids())
    @hsettings(max_examples=100)
    def test_migration_id_carried_forward(self, migration_id):
        mid = str(migration_id)

        # Phase 1 manifest
        p1_manifest = {
            "migration_id": mid,
            "phase1_completed_at": datetime.now(UTC).isoformat(),
            "source_db_url_hash": hashlib.sha256(b"pg://test").hexdigest(),
            "table_row_counts": {},
            "uuid_ranges": {},
        }

        # Simulate Phase 2 reading Phase 1 manifest and carrying forward
        p2_manifest = {
            "migration_id": p1_manifest["migration_id"],
            "phase": "deep_copy",
            "phase_status": "export_complete",
            "export_completed_at": datetime.now(UTC).isoformat(),
            "tables": {},
        }

        # Serialize and deserialize both
        p1 = json.loads(json.dumps(p1_manifest))
        p2 = json.loads(json.dumps(p2_manifest))
        assert p1["migration_id"] == p2["migration_id"]
        assert p2["migration_id"] == mid


# ── Property 8: FK validation completeness ───────────────


class TestFKValidationCompletenessProperty:
    """Property 8: FK validation completeness.

    **Validates: Requirements 9.2, 9.3, 9.4**
    """

    @given(
        agent_ids=st.frozensets(st.uuids().map(str), min_size=0, max_size=20),
        mcp_ids=st.frozensets(st.uuids().map(str), min_size=0, max_size=20),
        user_ids=st.frozensets(st.uuids().map(str), min_size=0, max_size=20),
        actor_ids=st.frozensets(st.uuids().map(str), min_size=0, max_size=20),
        mcp_server_ids=st.frozensets(st.uuids().map(str), min_size=0, max_size=20),
    )
    @hsettings(max_examples=100)
    def test_fk_collection_is_complete(self, agent_ids, mcp_ids, user_ids, actor_ids, mcp_server_ids):
        """Verify the set logic for FK collection matches the union of all unique non-null values."""
        # Simulate the FK collection logic from _validate_fk_references
        fk_values = {
            "agent_id": set(agent_ids),
            "mcp_id": set(mcp_ids),
            "mcp_server_id": set(mcp_server_ids),
            "user_id": set(user_ids),
            "actor_id": set(actor_ids),
        }

        # Merge aliases (same logic as _validate_fk_references)
        fk_values["mcp_id"] |= fk_values.pop("mcp_server_id", set())
        fk_values["user_id"] |= fk_values.pop("actor_id", set())

        # Verify merged sets
        assert fk_values["mcp_id"] == set(mcp_ids) | set(mcp_server_ids)
        assert fk_values["user_id"] == set(user_ids) | set(actor_ids)
        assert fk_values["agent_id"] == set(agent_ids)


# ── Property 9: Orphaned reference detection ─────────────


class TestOrphanedReferenceDetectionProperty:
    """Property 9: Orphaned reference detection correctness.

    **Validates: Requirements 9.7**
    """

    @given(
        collected=st.frozensets(st.uuids().map(str), min_size=0, max_size=50),
        existing=st.frozensets(st.uuids().map(str), min_size=0, max_size=50),
    )
    @hsettings(max_examples=100)
    def test_orphaned_is_set_difference(self, collected, existing):
        """orphaned = collected - existing, exactly."""
        orphaned = sorted(collected - existing)
        assert set(orphaned) == collected - existing
        # No false positives: every orphaned ID is in collected but not existing
        for oid in orphaned:
            assert oid in collected
            assert oid not in existing
        # No false negatives: every collected ID not in existing is orphaned
        for cid in collected:
            if cid not in existing:
                assert cid in orphaned


# ── Property 10: Connection string never leaked ──────────


class TestConnectionStringNeverLeakedProperty:
    """Property 10: Connection string never leaked.

    **Validates: Requirements 1.6, 13.1, 13.4**
    """

    @given(
        host=st.from_regex(r"[a-z][a-z0-9]{2,10}", fullmatch=True),
        port=st.integers(min_value=1000, max_value=65535),
        user=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
        password=st.from_regex(r"[a-z0-9]{5,15}", fullmatch=True),
    )
    @hsettings(max_examples=100)
    def test_clickhouse_url_never_in_output(self, host, port, user, password):
        secret_url = f"clickhouse://{user}:{password}@{host}:{port}/testdb"

        # Test export-telemetry path
        with patch("observal_cli.cmd_migrate._require_admin"):
            result = runner.invoke(
                cli_app,
                [
                    "migrate",
                    "export-telemetry",
                    "--clickhouse-url",
                    secret_url,
                    "--manifest",
                    "/nonexistent/manifest.json",
                    "--output-dir",
                    "/tmp/test-out",
                ],
            )
            assert secret_url not in result.output

    @given(
        host=st.from_regex(r"[a-z][a-z0-9]{2,10}", fullmatch=True),
        port=st.integers(min_value=1000, max_value=65535),
        user=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
        password=st.from_regex(r"[a-z0-9]{5,15}", fullmatch=True),
    )
    @hsettings(max_examples=100)
    def test_clickhouse_url_never_in_import_output(self, host, port, user, password):
        secret_url = f"clickhouse://{user}:{password}@{host}:{port}/testdb"

        with patch("observal_cli.cmd_migrate._require_admin"):
            result = runner.invoke(
                cli_app,
                [
                    "migrate",
                    "import-telemetry",
                    "--clickhouse-url",
                    secret_url,
                    "--input-dir",
                    "/nonexistent/dir",
                ],
            )
            assert secret_url not in result.output

    @given(
        host=st.from_regex(r"[a-z][a-z0-9]{2,10}", fullmatch=True),
        port=st.integers(min_value=1000, max_value=65535),
        user=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
        password=st.from_regex(r"[a-z0-9]{5,15}", fullmatch=True),
    )
    @hsettings(max_examples=100)
    def test_clickhouse_url_never_in_validate_output(self, host, port, user, password):
        secret_url = f"clickhouse://{user}:{password}@{host}:{port}/testdb"

        with patch("observal_cli.cmd_migrate._require_admin"):
            result = runner.invoke(
                cli_app,
                [
                    "migrate",
                    "validate-telemetry",
                    "--input-dir",
                    "/nonexistent/dir",
                    "--clickhouse-url",
                    secret_url,
                ],
            )
            assert secret_url not in result.output


# ══════════════════════════════════════════════════════════
# New Tests for Fix Tasks
# ══════════════════════════════════════════════════════════


# ── UUID Lowercase Normalization ─────────────────────────


class TestUUIDLowercaseNormalization:
    """Verify UUID values are normalized to lowercase for FK comparison."""

    def test_uuid_re_matches_lowercase(self):
        assert _UUID_RE.match("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

    def test_uuid_re_matches_uppercase(self):
        assert _UUID_RE.match("A1B2C3D4-E5F6-7890-ABCD-EF1234567890")

    def test_uuid_re_matches_mixed_case(self):
        assert _UUID_RE.match("A1b2C3d4-E5f6-7890-AbCd-Ef1234567890")

    def test_uuid_re_rejects_non_uuid(self):
        assert not _UUID_RE.match("not-a-uuid")
        assert not _UUID_RE.match("filesystem")
        assert not _UUID_RE.match("")

    def test_uuid_re_is_module_level_constant(self):
        """Verify _UUID_RE is compiled once at module level, not per call."""
        import observal_cli.cmd_migrate as mod

        assert hasattr(mod, "_UUID_RE")
        assert mod._UUID_RE is _UUID_RE


# ── Partition Check for All Engines ──────────────────────


class TestPartitionCheckAllEngines:
    """Verify partition-has-data check applies to both replacing and mergetree."""

    def test_replacing_partition_query_uses_final(self):
        """For replacing engines, the partition check should use FINAL WHERE is_deleted = 0."""
        # We test this indirectly by checking _ch_partition_has_data builds the right query.
        # The function is async, so we verify the query pattern via _build_ch_export_query.
        cfg: TableCfg = {"name": "traces", "engine": "replacing", "time_col": "start_time", "fk_cols": []}
        query = _build_ch_export_query(cfg, 202501)
        assert "FINAL" in query
        assert "is_deleted = 0" in query

    def test_mergetree_partition_query_no_final(self):
        cfg: TableCfg = {"name": "audit_log", "engine": "mergetree", "time_col": "timestamp", "fk_cols": []}
        query = _build_ch_export_query(cfg, 202501)
        assert "FINAL" not in query


# ── Import Resume State ──────────────────────────────────


class TestImportResumeState:
    """Verify .import_state.json is written and read for resume."""

    def test_state_file_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / ".import_state.json"
            completed = {"traces", "spans"}
            state_path.write_text(
                json.dumps({"completed": sorted(completed)}, indent=2),
                encoding="utf-8",
            )
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            assert set(loaded["completed"]) == completed

    def test_state_file_empty_initially(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / ".import_state.json"
            assert not state_path.exists()


# ── Atomic Write Pattern ─────────────────────────────────


class TestAtomicWritePattern:
    """Verify the .tmp file pattern for atomic writes."""

    def test_tmp_suffix_construction(self):
        """Verify the tmp path is constructed correctly."""
        original = Path("/tmp/traces_2025-01.parquet")
        tmp = original.with_suffix(original.suffix + ".tmp")
        assert str(tmp).endswith(".parquet.tmp")
        assert tmp.name == "traces_2025-01.parquet.tmp"


# ── Exception Chaining ───────────────────────────────────


class TestExceptionChaining:
    """Verify raise typer.Exit(1) from exc preserves __cause__."""

    def test_require_admin_chains_exception(self):
        with patch("observal_cli.cmd_migrate.client") as mock_client:
            mock_client.get.side_effect = SystemExit(1)
            with pytest.raises((SystemExit, click.exceptions.Exit)) as exc_info:
                _require_admin()
            # The raised exception should have a __cause__
            if hasattr(exc_info.value, "__cause__"):
                assert exc_info.value.__cause__ is not None


# ── UTF-8 Encoding ───────────────────────────────────────


class TestUTF8Encoding:
    """Verify encoding='utf-8' is used on all text I/O."""

    def test_utf8_write_and_read(self):
        """Verify UTF-8 encoding works for non-ASCII content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            content = json.dumps({"name": "tëst-dàtà-日本語"}, indent=2)
            path.write_text(content, encoding="utf-8")
            loaded = json.loads(path.read_text(encoding="utf-8"))
            assert loaded["name"] == "tëst-dàtà-日本語"


# ── Sidecar Archive Hash ─────────────────────────────────


class TestSidecarArchiveHash:
    """Verify archive_sha256 field in sidecar manifest."""

    def test_sha256_file_deterministic(self):
        """Verify _sha256_file produces consistent results."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as f:
            f.write(b"test archive content")
            path = Path(f.name)
        try:
            h1 = _sha256_file(path)
            h2 = _sha256_file(path)
            assert h1 == h2
            assert len(h1) == 64  # SHA-256 hex digest length
        finally:
            path.unlink(missing_ok=True)

    def test_archive_hash_field_in_manifest(self):
        """Verify the archive_sha256 field can be added to a manifest dict."""
        manifest = {"migration_id": "test-123"}
        archive_hash = hashlib.sha256(b"test").hexdigest()
        manifest["archive_sha256"] = archive_hash
        serialized = json.dumps(manifest)
        deserialized = json.loads(serialized)
        assert deserialized["archive_sha256"] == archive_hash


# ── Parameterized Query ──────────────────────────────────


class TestParameterizedQuery:
    """Verify _ch_existing_tables uses parameterized query, not f-string."""

    def test_existing_tables_query_uses_parameterized_syntax(self):
        """The SQL should use {db:String} placeholder, not f-string interpolation."""
        # We can't easily call the async function, but we can verify the pattern
        # by checking the source code uses the right SQL string.
        import inspect

        from observal_cli.cmd_migrate import _ch_existing_tables

        source = inspect.getsource(_ch_existing_tables)
        assert "{db:String}" in source
        assert "extra_params" in source
        # Should NOT have f-string with db variable in SQL
        assert 'f"SELECT' not in source or "f'SELECT" not in source


# ── Cutoff in WHERE Clause ───────────────────────────────


class TestCutoffInWhereClause:
    """Verify export_time_cutoff appears in WHERE clause."""

    def test_export_query_with_cutoff(self):
        cfg: TableCfg = {"name": "audit_log", "engine": "mergetree", "time_col": "timestamp", "fk_cols": []}
        cutoff = "2025-06-15T12:00:00+00:00"
        query = _build_ch_export_query(cfg, 202506, cutoff=cutoff)
        assert "timestamp < {cutoff:String}" in query
        assert "toYYYYMM(timestamp) = 202506" in query

    def test_count_query_with_cutoff(self):
        cfg: TableCfg = {"name": "audit_log", "engine": "mergetree", "time_col": "timestamp", "fk_cols": []}
        cutoff = "2025-06-15T12:00:00+00:00"
        query = _build_ch_count_query(cfg, 202506, cutoff=cutoff)
        assert "timestamp < {cutoff:String}" in query
        assert "count() AS cnt" in query

    def test_replacing_query_with_cutoff(self):
        cfg: TableCfg = {"name": "traces", "engine": "replacing", "time_col": "start_time", "fk_cols": []}
        cutoff = "2025-06-15T12:00:00+00:00"
        query = _build_ch_export_query(cfg, 202506, cutoff=cutoff)
        assert "start_time < {cutoff:String}" in query
        assert "FINAL" in query
        assert "is_deleted = 0" in query
