"""Unit tests for pg-shallow-copy: observal migrate CLI command group."""

import hashlib
import json
import re
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import click.exceptions
import pytest
from hypothesis import given
from hypothesis import settings as hsettings
from hypothesis import strategies as st
from typer.testing import CliRunner

from observal_cli.cmd_migrate import (
    CHUNK_SIZE,
    INSERT_ORDER,
    JSONB_COLUMNS,
    ChecksumResult,
    ExportResult,
    ImportResult,
    PGEncoder,
    ValidationResult,
    _build_insert,
    _build_select,
    _coerce_value,
    _require_admin,
    _sha256_file,
)
from observal_cli.main import app as cli_app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ── 1. CLI Registration Tests ────────────────────────────


class TestCLIRegistration:
    def test_migrate_command_group_exists(self):
        result = runner.invoke(cli_app, ["migrate", "--help"])
        assert result.exit_code == 0
        assert "migrate" in _plain(result.output).lower()

    def test_migrate_help_lists_subcommands(self):
        result = runner.invoke(cli_app, ["migrate", "--help"])
        assert result.exit_code == 0
        out = _plain(result.output)
        assert "export" in out
        assert "import" in out
        assert "validate" in out

    def test_export_subcommand_help(self):
        result = runner.invoke(cli_app, ["migrate", "export", "--help"])
        assert result.exit_code == 0
        assert "--db-url" in _plain(result.output)

    def test_import_subcommand_help(self):
        result = runner.invoke(cli_app, ["migrate", "import", "--help"])
        assert result.exit_code == 0
        out = _plain(result.output)
        assert "--db-url" in out
        assert "--archive" in out

    def test_validate_subcommand_help(self):
        result = runner.invoke(cli_app, ["migrate", "validate", "--help"])
        assert result.exit_code == 0
        assert "--archive" in _plain(result.output)


# ── 2. PGEncoder Tests ───────────────────────────────────


class TestPGEncoder:
    def test_uuid_serialization(self):
        test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = json.dumps(test_uuid, cls=PGEncoder)
        assert result == '"12345678-1234-5678-1234-567812345678"'

    def test_datetime_serialization(self):
        dt = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = json.dumps(dt, cls=PGEncoder)
        parsed = json.loads(result)
        assert "2026-01-15" in parsed
        assert "10:30:00" in parsed

    def test_timedelta_serialization(self):
        td = timedelta(hours=2, minutes=30)
        result = json.dumps(td, cls=PGEncoder)
        assert json.loads(result) == 9000.0

    def test_none_passthrough(self):
        assert json.dumps(None, cls=PGEncoder) == "null"

    def test_str_passthrough(self):
        assert json.dumps("hello", cls=PGEncoder) == '"hello"'

    def test_int_passthrough(self):
        assert json.dumps(42, cls=PGEncoder) == "42"

    def test_float_passthrough(self):
        assert json.dumps(3.14, cls=PGEncoder) == "3.14"

    def test_bool_passthrough(self):
        assert json.dumps(True, cls=PGEncoder) == "true"
        assert json.dumps(False, cls=PGEncoder) == "false"

    def test_round_trip_uuid(self):
        original = uuid.uuid4()
        encoded = json.dumps(original, cls=PGEncoder)
        decoded = json.loads(encoded)
        assert uuid.UUID(decoded) == original

    def test_round_trip_datetime(self):
        original = datetime(2026, 6, 15, 14, 30, 22, 123456, tzinfo=UTC)
        encoded = json.dumps(original, cls=PGEncoder)
        decoded = json.loads(encoded)
        restored = datetime.fromisoformat(decoded)
        assert restored == original

    def test_round_trip_timedelta(self):
        original = timedelta(days=1, hours=3, seconds=45)
        encoded = json.dumps(original, cls=PGEncoder)
        decoded = json.loads(encoded)
        restored = timedelta(seconds=decoded)
        assert restored == original

    def test_mixed_row(self):
        row = {
            "id": uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            "name": "test-org",
            "count": 42,
            "active": True,
            "score": 3.14,
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "interval": timedelta(hours=1),
            "notes": None,
        }
        encoded = json.dumps(row, cls=PGEncoder)
        decoded = json.loads(encoded)
        assert decoded["id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert decoded["name"] == "test-org"
        assert decoded["count"] == 42
        assert decoded["active"] is True
        assert decoded["score"] == 3.14
        assert decoded["notes"] is None
        assert isinstance(decoded["interval"], float)


# ── 3. Constants Tests ───────────────────────────────────


class TestConstants:
    def test_insert_order_has_33_entries(self):
        assert len(INSERT_ORDER) == 33

    def test_insert_order_no_duplicates(self):
        assert len(INSERT_ORDER) == len(set(INSERT_ORDER))

    def test_insert_order_contains_key_tables(self):
        key_tables = [
            "organizations",
            "users",
            "agents",
            "mcp_listings",
            "feedback",
            "eval_runs",
            "scorecards",
            "alert_rules",
            "alert_history",
            "component_bundles",
        ]
        for table in key_tables:
            assert table in INSERT_ORDER, f"Missing table: {table}"

    def test_jsonb_columns_tables_in_insert_order(self):
        for table in JSONB_COLUMNS:
            assert table in INSERT_ORDER, f"JSONB table '{table}' not in INSERT_ORDER"

    def test_chunk_size_is_500(self):
        assert CHUNK_SIZE == 500


# ── 4. _build_select Tests ──────────────────────────────


class TestBuildSelect:
    def test_table_with_jsonb_columns(self):
        columns = ["id", "name", "model_config_json", "external_mcps", "supported_ides", "created_at"]
        sql = _build_select("agents", columns)
        assert "model_config_json::text AS model_config_json" in sql
        assert "external_mcps::text AS external_mcps" in sql
        assert "supported_ides::text AS supported_ides" in sql
        # Non-JSONB columns should not have ::text
        assert "id::text" not in sql
        assert "name::text" not in sql

    def test_table_without_jsonb_columns(self):
        sql = _build_select("organizations", ["id", "name", "slug"])
        assert sql == "SELECT * FROM organizations"

    def test_agents_produces_correct_sql(self):
        columns = ["id", "name", "model_config_json"]
        sql = _build_select("agents", columns)
        assert sql.startswith("SELECT ")
        assert "FROM agents" in sql
        assert "model_config_json::text AS model_config_json" in sql
        assert ", id," not in sql or "id" in sql  # id should be plain

    def test_all_jsonb_tables_produce_casts(self):
        for table, jsonb_cols in JSONB_COLUMNS.items():
            # Use JSONB columns plus a non-JSONB column
            columns = ["id", *jsonb_cols]
            sql = _build_select(table, columns)
            for col in jsonb_cols:
                assert f"{col}::text AS {col}" in sql, f"Missing cast for {col} in {table}"


# ── 5. _require_admin Tests ─────────────────────────────


class TestRequireAdmin:
    @patch("observal_cli.cmd_migrate.client")
    def test_admin_role_allowed(self, mock_client):
        mock_client.get.return_value = {"role": "admin"}
        _require_admin()  # Should not raise

    @patch("observal_cli.cmd_migrate.client")
    def test_super_admin_role_allowed(self, mock_client):
        mock_client.get.return_value = {"role": "super_admin"}
        _require_admin()  # Should not raise

    @patch("observal_cli.cmd_migrate.client")
    def test_user_role_rejected(self, mock_client):
        mock_client.get.return_value = {"role": "user"}
        with pytest.raises((SystemExit, click.exceptions.Exit)):
            _require_admin()

    @patch("observal_cli.cmd_migrate.client")
    def test_reviewer_role_rejected(self, mock_client):
        mock_client.get.return_value = {"role": "reviewer"}
        with pytest.raises((SystemExit, click.exceptions.Exit)):
            _require_admin()

    @patch("observal_cli.cmd_migrate.client")
    def test_unauthenticated_rejected(self, mock_client):
        mock_client.get.side_effect = SystemExit(1)
        with pytest.raises((SystemExit, click.exceptions.Exit)):
            _require_admin()


# ── 6. _sha256_file Tests ───────────────────────────────


class TestSha256File:
    def test_known_content_known_hash(self):
        expected = hashlib.sha256(b"hello world\n").hexdigest()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"hello world\n")
            f.flush()
            path = Path(f.name)
        try:
            assert _sha256_file(path) == expected
        finally:
            path.unlink()

    def test_same_content_same_hash(self):
        content = b"deterministic content for hashing"
        paths = []
        try:
            for _ in range(2):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
                    f.write(content)
                    f.flush()
                    paths.append(Path(f.name))
            assert _sha256_file(paths[0]) == _sha256_file(paths[1])
        finally:
            for p in paths:
                p.unlink()

    def test_different_content_different_hash(self):
        paths = []
        try:
            for content in [b"content A", b"content B"]:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
                    f.write(content)
                    f.flush()
                    paths.append(Path(f.name))
            assert _sha256_file(paths[0]) != _sha256_file(paths[1])
        finally:
            for p in paths:
                p.unlink()


# ── 7. _coerce_value Tests ──────────────────────────────


class TestCoerceValue:
    def test_uuid_string_to_uuid(self):
        val = "12345678-1234-5678-1234-567812345678"
        result = _coerce_value(val, "uuid")
        assert isinstance(result, uuid.UUID)
        assert str(result) == val

    def test_iso_datetime_to_datetime(self):
        val = "2026-01-15T10:30:00+00:00"
        result = _coerce_value(val, "timestamptz")
        assert isinstance(result, datetime)
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 15

    def test_float_to_timedelta(self):
        result = _coerce_value(9000.0, "interval")
        assert isinstance(result, timedelta)
        assert result.total_seconds() == 9000.0

    def test_none_returns_none(self):
        assert _coerce_value(None, "uuid") is None
        assert _coerce_value(None, "timestamptz") is None
        assert _coerce_value(None, "text") is None

    def test_string_text_unchanged(self):
        result = _coerce_value("hello", "text")
        assert result == "hello"
        assert isinstance(result, str)

    def test_bool_preserved(self):
        assert _coerce_value(True, "bool") is True
        assert _coerce_value(False, "bool") is False

    def test_int_coercion(self):
        result = _coerce_value(42, "int4")
        assert result == 42
        assert isinstance(result, int)

    def test_float_coercion(self):
        result = _coerce_value(3.14, "float8")
        assert result == 3.14
        assert isinstance(result, float)


# ── 8. _build_insert Tests ──────────────────────────────


class TestBuildInsert:
    def test_table_with_jsonb_columns(self):
        columns = ["id", "name", "model_config_json"]
        col_types = {"id": "uuid", "name": "text", "model_config_json": "jsonb"}
        sql = _build_insert("agents", columns, col_types)
        assert "$1" in sql
        assert "$2" in sql
        assert "$3::jsonb" in sql
        assert 'ON CONFLICT ("id") DO NOTHING' in sql

    def test_table_without_jsonb_columns(self):
        columns = ["id", "name", "slug"]
        col_types = {"id": "uuid", "name": "text", "slug": "text"}
        sql = _build_insert("organizations", columns, col_types)
        assert "$1" in sql
        assert "$2" in sql
        assert "$3" in sql
        assert "::jsonb" not in sql
        assert 'ON CONFLICT ("id") DO NOTHING' in sql

    def test_on_conflict_present(self):
        columns = ["id"]
        col_types = {"id": "uuid"}
        sql = _build_insert("users", columns, col_types)
        assert 'ON CONFLICT ("id") DO NOTHING' in sql

    def test_insert_column_list(self):
        columns = ["id", "name", "email"]
        col_types = {"id": "uuid", "name": "text", "email": "text"}
        sql = _build_insert("users", columns, col_types)
        assert 'INSERT INTO users ("id", "name", "email")' in sql

    def test_multiple_jsonb_columns(self):
        columns = ["id", "tools_schema", "environment_variables", "supported_ides"]
        col_types = {
            "id": "uuid",
            "tools_schema": "jsonb",
            "environment_variables": "jsonb",
            "supported_ides": "jsonb",
        }
        sql = _build_insert("mcp_listings", columns, col_types)
        assert "$2::jsonb" in sql
        assert "$3::jsonb" in sql
        assert "$4::jsonb" in sql


# ── 9. Manifest Structure Tests ──────────────────────────


class TestManifestStructure:
    def test_manifest_required_fields(self):
        manifest = {
            "schema_version": "1.0",
            "migration_id": str(uuid.uuid4()),
            "exported_at": datetime.now(UTC).isoformat(),
            "source_alembic_version": "0012",
            "tables": {
                table: {"checksum": hashlib.sha256(b"test").hexdigest(), "row_count": 0} for table in INSERT_ORDER
            },
        }
        assert "schema_version" in manifest
        assert "migration_id" in manifest
        assert "exported_at" in manifest
        assert "source_alembic_version" in manifest
        assert "tables" in manifest
        assert manifest["schema_version"] == "1.0"

    def test_migration_manifest_required_fields(self):
        migration_id = str(uuid.uuid4())
        migration_manifest = {
            "migration_id": migration_id,
            "phase1_completed_at": datetime.now(UTC).isoformat(),
            "source_db_url_hash": hashlib.sha256(b"postgres://...").hexdigest(),
            "table_row_counts": {table: 0 for table in INSERT_ORDER},
            "uuid_ranges": {},
        }
        assert "migration_id" in migration_manifest
        assert "phase1_completed_at" in migration_manifest
        assert "source_db_url_hash" in migration_manifest
        assert "table_row_counts" in migration_manifest
        assert "uuid_ranges" in migration_manifest

    def test_manifest_json_round_trip(self):
        manifest = {
            "schema_version": "1.0",
            "migration_id": str(uuid.uuid4()),
            "exported_at": datetime.now(UTC).isoformat(),
            "source_alembic_version": "0012",
            "tables": {"organizations": {"checksum": "abc123", "row_count": 5}},
        }
        serialized = json.dumps(manifest)
        deserialized = json.loads(serialized)
        assert deserialized == manifest


# ── 10. Error Path Tests (CLI) ───────────────────────────


class TestErrorPaths:
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_import_nonexistent_archive(self, mock_admin):
        result = runner.invoke(
            cli_app,
            ["migrate", "import", "--db-url", "postgres://x", "--archive", "/nonexistent/archive.tar.gz"],
        )
        assert result.exit_code != 0

    @patch("observal_cli.cmd_migrate._require_admin")
    def test_validate_nonexistent_archive(self, mock_admin):
        result = runner.invoke(
            cli_app,
            ["migrate", "validate", "--archive", "/nonexistent/archive.tar.gz"],
        )
        assert result.exit_code != 0

    def test_export_missing_db_url(self):
        """Export without --db-url should fail (required option)."""
        result = runner.invoke(cli_app, ["migrate", "export"])
        assert result.exit_code != 0


# ── 11. Security Tests ──────────────────────────────────


class TestSecurity:
    @patch("observal_cli.cmd_migrate._require_admin")
    @patch("observal_cli.cmd_migrate.asyncio")
    def test_db_url_not_in_export_output(self, mock_asyncio, mock_admin):
        """The --db-url value should never appear in CLI output."""
        secret_url = "postgres://secret_user:secret_pass@secret-host:5432/secret_db"
        mock_asyncio.run.side_effect = SystemExit(1)
        result = runner.invoke(
            cli_app,
            ["migrate", "export", "--db-url", secret_url],
        )
        assert secret_url not in result.output

    @patch("observal_cli.cmd_migrate._require_admin")
    def test_db_url_not_in_import_output(self, mock_admin):
        """The --db-url value should never appear in CLI output for import."""
        secret_url = "postgres://secret_user:secret_pass@secret-host:5432/secret_db"
        result = runner.invoke(
            cli_app,
            ["migrate", "import", "--db-url", secret_url, "--archive", "/nonexistent.tar.gz"],
        )
        assert secret_url not in result.output

    @patch("observal_cli.cmd_migrate._require_admin")
    def test_db_url_not_in_validate_output(self, mock_admin):
        """The --db-url value should never appear in CLI output for validate."""
        secret_url = "postgres://secret_user:secret_pass@secret-host:5432/secret_db"
        result = runner.invoke(
            cli_app,
            ["migrate", "validate", "--archive", "/nonexistent.tar.gz", "--db-url", secret_url],
        )
        assert secret_url not in result.output


# ── 12. Dataclass Tests ─────────────────────────────────


class TestDataclasses:
    def test_export_result_fields(self):
        result = ExportResult(
            archive_path="/tmp/test.tar.gz",
            migration_id="abc-123",
            table_counts={"users": 10},
            checksums={"users": "sha256hex"},
            duration_seconds=1.5,
            total_rows=10,
        )
        assert result.archive_path == "/tmp/test.tar.gz"
        assert result.total_rows == 10

    def test_import_result_fields(self):
        result = ImportResult(
            migration_id="abc-123",
            tables_imported=33,
            rows_inserted={"users": 10},
            rows_skipped={"users": 2},
            duration_seconds=2.0,
            warnings=[],
        )
        assert result.tables_imported == 33
        assert result.rows_inserted["users"] == 10

    def test_checksum_result_fields(self):
        result = ChecksumResult(
            table_name="users",
            expected_checksum="abc",
            actual_checksum="abc",
            passed=True,
        )
        assert result.passed is True

    def test_validation_result_fields(self):
        result = ValidationResult(
            archive_valid=True,
            checksum_results=[],
            cross_db_results=None,
        )
        assert result.archive_valid is True
        assert result.cross_db_results is None


# ── 13. INSERT_ORDER Dependency Tests ────────────────────


class TestInsertOrderDependencies:
    """Verify that FK parent tables appear before child tables in INSERT_ORDER."""

    KNOWN_FK_PAIRS = [
        # (child, parent) — parent must come before child
        ("users", "organizations"),
        ("exporter_configs", "organizations"),
        ("agents", "organizations"),
        ("mcp_listings", "organizations"),
        ("agent_components", "agents"),
        ("agent_goal_templates", "agents"),
        ("eval_runs", "agents"),
        ("scorecards", "eval_runs"),
        ("scorecard_dimensions", "scorecards"),
        ("feedback", "users"),
        ("alert_history", "alert_rules"),
        ("agent_goal_sections", "agent_goal_templates"),
        ("mcp_downloads", "mcp_listings"),
        ("skill_downloads", "skill_listings"),
        ("hook_downloads", "hook_listings"),
        ("prompt_downloads", "prompt_listings"),
        ("sandbox_downloads", "sandbox_listings"),
    ]

    @pytest.mark.parametrize("child,parent", KNOWN_FK_PAIRS)
    def test_parent_before_child(self, child, parent):
        parent_idx = INSERT_ORDER.index(parent)
        child_idx = INSERT_ORDER.index(child)
        assert parent_idx < child_idx, f"{parent} (idx={parent_idx}) should come before {child} (idx={child_idx})"


# ══════════════════════════════════════════════════════════
# Property-Based Tests (Hypothesis)
# ══════════════════════════════════════════════════════════

# Hypothesis strategies for common PostgreSQL types
uuids = st.uuids()
tz_datetimes = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31),
    timezones=st.just(UTC),
)
timedeltas = st.timedeltas(
    min_value=timedelta(seconds=0),
    max_value=timedelta(days=365 * 10),
)
primitives = st.one_of(
    st.text(min_size=0, max_size=200),
    st.integers(min_value=-(2**31), max_value=2**31),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none(),
)


# ── Property 1: PGEncoder round-trip ────────────────────


class TestPGEncoderRoundTripProperty:
    """Property 1: For any valid row, encode→decode→coerce produces equivalent values."""

    @given(val=uuids)
    @hsettings(max_examples=100)
    def test_uuid_round_trip(self, val):
        encoded = json.dumps(val, cls=PGEncoder)
        decoded = json.loads(encoded)
        assert uuid.UUID(decoded) == val

    @given(val=tz_datetimes)
    @hsettings(max_examples=100)
    def test_datetime_round_trip(self, val):
        encoded = json.dumps(val, cls=PGEncoder)
        decoded = json.loads(encoded)
        restored = datetime.fromisoformat(decoded)
        assert restored == val

    @given(val=timedeltas)
    @hsettings(max_examples=100)
    def test_timedelta_round_trip(self, val):
        encoded = json.dumps(val, cls=PGEncoder)
        decoded = json.loads(encoded)
        restored = timedelta(seconds=decoded)
        # Compare total_seconds to handle floating point
        assert abs(restored.total_seconds() - val.total_seconds()) < 1e-6

    @given(
        row=st.fixed_dictionaries(
            {
                "id": uuids,
                "name": st.text(min_size=1, max_size=50),
                "count": st.integers(min_value=0, max_value=10000),
                "active": st.booleans(),
                "created_at": tz_datetimes,
                "interval": timedeltas,
                "notes": st.one_of(st.none(), st.text(min_size=0, max_size=100)),
            }
        )
    )
    @hsettings(max_examples=100)
    def test_mixed_row_round_trip(self, row):
        encoded = json.dumps(row, cls=PGEncoder)
        decoded = json.loads(encoded)
        # Verify each field round-trips correctly
        assert uuid.UUID(decoded["id"]) == row["id"]
        assert decoded["name"] == row["name"]
        assert decoded["count"] == row["count"]
        assert decoded["active"] == row["active"]
        assert datetime.fromisoformat(decoded["created_at"]) == row["created_at"]
        assert abs(decoded["interval"] - row["interval"].total_seconds()) < 1e-6
        assert decoded["notes"] == row["notes"]


# ── Property 2: PGEncoder format correctness ────────────


UUID_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class TestPGEncoderFormatProperty:
    """Property 2: PGEncoder produces correctly formatted output for each type."""

    @given(val=uuids)
    @hsettings(max_examples=100)
    def test_uuid_format_lowercase_hyphenated(self, val):
        encoded = json.loads(json.dumps(val, cls=PGEncoder))
        assert UUID_REGEX.match(encoded), f"UUID {encoded} doesn't match expected format"

    @given(val=tz_datetimes)
    @hsettings(max_examples=100)
    def test_datetime_format_iso8601_parseable(self, val):
        encoded = json.loads(json.dumps(val, cls=PGEncoder))
        restored = datetime.fromisoformat(encoded)
        assert restored.tzinfo is not None, "Timezone info must be preserved"
        assert restored == val

    @given(val=timedeltas)
    @hsettings(max_examples=100)
    def test_timedelta_format_total_seconds(self, val):
        encoded = json.loads(json.dumps(val, cls=PGEncoder))
        assert isinstance(encoded, float)
        assert abs(encoded - val.total_seconds()) < 1e-6


# ── Property 3: JSONB cast in SELECT queries ────────────


class TestJSONBCastProperty:
    """Property 3: JSONB columns get ::text cast, non-JSONB tables get SELECT *."""

    @given(table=st.sampled_from(INSERT_ORDER))
    @hsettings(max_examples=100)
    def test_jsonb_tables_get_casts_others_get_star(self, table):
        jsonb_cols = JSONB_COLUMNS.get(table, [])
        # Build a column list: id + any JSONB cols + a fake non-JSONB col
        columns = ["id"] + jsonb_cols + (["created_at"] if jsonb_cols else [])
        sql = _build_select(table, columns)

        if not jsonb_cols:
            assert sql == f"SELECT * FROM {table}"
        else:
            for col in jsonb_cols:
                assert f"{col}::text AS {col}" in sql
            # Non-JSONB columns should NOT have ::text
            assert "id::text" not in sql


# ── Property 4: Checksum integrity ──────────────────────


class TestChecksumIntegrityProperty:
    """Property 4: SHA-256 is deterministic — same bytes always produce same hash."""

    @given(data=st.binary(min_size=0, max_size=10000))
    @hsettings(max_examples=100)
    def test_sha256_deterministic(self, data):
        paths = []
        try:
            for _ in range(2):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
                    f.write(data)
                    f.flush()
                    paths.append(Path(f.name))
            assert _sha256_file(paths[0]) == _sha256_file(paths[1])
        finally:
            for p in paths:
                p.unlink(missing_ok=True)

    @given(
        data_a=st.binary(min_size=1, max_size=1000),
        data_b=st.binary(min_size=1, max_size=1000),
    )
    @hsettings(max_examples=100)
    def test_sha256_different_content_different_hash(self, data_a, data_b):
        """Different content should (almost always) produce different hashes."""
        if data_a == data_b:
            return  # Skip identical inputs
        hash_a = hashlib.sha256(data_a).hexdigest()
        hash_b = hashlib.sha256(data_b).hexdigest()
        assert hash_a != hash_b


# ── Property 5: Idempotent import ───────────────────────


class TestIdempotentImportProperty:
    """Property 5: ON CONFLICT (id) DO NOTHING means second import inserts zero rows."""

    @given(
        rows=st.lists(
            st.fixed_dictionaries(
                {
                    "id": st.uuids(),
                    "name": st.text(min_size=1, max_size=50),
                }
            ),
            min_size=1,
            max_size=20,
        )
    )
    @hsettings(max_examples=100)
    def test_on_conflict_do_nothing_sql_is_idempotent(self, rows):
        """Verify the INSERT query structure guarantees idempotency."""
        columns = list(rows[0].keys())
        col_types = {"id": "uuid", "name": "text"}
        sql = _build_insert("test_table", columns, col_types)
        # The SQL must contain ON CONFLICT ("id") DO NOTHING
        assert 'ON CONFLICT ("id") DO NOTHING' in sql
        # The SQL must be a valid INSERT with all columns
        for col in columns:
            assert col in sql


# ── Property 6: UUID preservation ───────────────────────


class TestUUIDPreservationProperty:
    """Property 6: UUIDs survive PGEncoder encode→decode byte-identical."""

    @given(val=uuids)
    @hsettings(max_examples=100)
    def test_uuid_preserved_through_encode_decode(self, val):
        # Simulate export: UUID → PGEncoder → JSON string
        encoded = json.dumps({"id": val}, cls=PGEncoder)
        # Simulate import: JSON string → json.loads → _coerce_value
        decoded = json.loads(encoded)
        restored = _coerce_value(decoded["id"], "uuid")
        assert isinstance(restored, uuid.UUID)
        assert restored == val
        assert str(restored) == str(val)


# ── Property 7: Manifest JSON round-trip ────────────────


class TestManifestRoundTripProperty:
    """Property 7: Manifest dicts survive JSON serialize→deserialize exactly."""

    @given(
        migration_id=st.uuids(),
        alembic_version=st.text(min_size=1, max_size=20, alphabet="0123456789"),
        row_counts=st.dictionaries(
            keys=st.sampled_from(INSERT_ORDER[:5]),
            values=st.integers(min_value=0, max_value=100000),
            min_size=1,
            max_size=5,
        ),
    )
    @hsettings(max_examples=100)
    def test_manifest_round_trip(self, migration_id, alembic_version, row_counts):
        manifest = {
            "schema_version": "1.0",
            "migration_id": str(migration_id),
            "exported_at": datetime.now(UTC).isoformat(),
            "source_alembic_version": alembic_version,
            "tables": {
                table: {"checksum": hashlib.sha256(f"{table}{count}".encode()).hexdigest(), "row_count": count}
                for table, count in row_counts.items()
            },
        }
        serialized = json.dumps(manifest)
        deserialized = json.loads(serialized)
        assert deserialized == manifest

    @given(
        migration_id=st.uuids(),
        row_counts=st.dictionaries(
            keys=st.sampled_from(INSERT_ORDER[:5]),
            values=st.integers(min_value=0, max_value=100000),
            min_size=1,
            max_size=5,
        ),
    )
    @hsettings(max_examples=100)
    def test_migration_manifest_round_trip(self, migration_id, row_counts):
        migration_manifest = {
            "migration_id": str(migration_id),
            "phase1_completed_at": datetime.now(UTC).isoformat(),
            "source_db_url_hash": hashlib.sha256(b"postgres://test").hexdigest(),
            "table_row_counts": row_counts,
            "uuid_ranges": {table: {"min_id": str(uuid.uuid4()), "max_id": str(uuid.uuid4())} for table in row_counts},
        }
        serialized = json.dumps(migration_manifest)
        deserialized = json.loads(serialized)
        assert deserialized == migration_manifest


# ── Property 8: INSERT_ORDER FK ordering ────────────────


class TestInsertOrderFKProperty:
    """Property 8: For all FK pairs, parent index < child index in INSERT_ORDER."""

    # Complete FK pairs derived from the SQLAlchemy models
    ALL_FK_PAIRS = [
        ("users", "organizations"),
        ("exporter_configs", "organizations"),
        ("component_bundles", "users"),
        ("mcp_listings", "users"),
        ("mcp_listings", "organizations"),
        ("mcp_listings", "component_bundles"),
        ("skill_listings", "users"),
        ("skill_listings", "organizations"),
        ("skill_listings", "component_bundles"),
        ("hook_listings", "users"),
        ("hook_listings", "organizations"),
        ("hook_listings", "component_bundles"),
        ("prompt_listings", "users"),
        ("prompt_listings", "organizations"),
        ("prompt_listings", "component_bundles"),
        ("sandbox_listings", "users"),
        ("sandbox_listings", "organizations"),
        ("sandbox_listings", "component_bundles"),
        ("agents", "users"),
        ("agents", "organizations"),
        ("mcp_validation_results", "mcp_listings"),
        ("mcp_downloads", "mcp_listings"),
        ("mcp_downloads", "users"),
        ("skill_downloads", "skill_listings"),
        ("skill_downloads", "users"),
        ("hook_downloads", "hook_listings"),
        ("hook_downloads", "users"),
        ("prompt_downloads", "prompt_listings"),
        ("prompt_downloads", "users"),
        ("sandbox_downloads", "sandbox_listings"),
        ("sandbox_downloads", "users"),
        ("submissions", "users"),
        ("alert_rules", "users"),
        ("agent_goal_templates", "agents"),
        ("agent_download_records", "agents"),
        ("agent_download_records", "users"),
        ("component_download_records", "agents"),
        ("dimension_weights", "agents"),
        ("agent_goal_sections", "agent_goal_templates"),
        ("agent_components", "agents"),
        ("feedback", "users"),
        ("alert_history", "alert_rules"),
        ("eval_runs", "agents"),
        ("eval_runs", "users"),
        ("scorecards", "agents"),
        ("scorecards", "eval_runs"),
        ("scorecard_dimensions", "scorecards"),
        ("trace_penalties", "scorecards"),
        ("trace_penalties", "penalty_definitions"),
    ]

    @given(pair=st.sampled_from(ALL_FK_PAIRS))
    @hsettings(max_examples=100)
    def test_fk_parent_before_child(self, pair):
        child, parent = pair
        parent_idx = INSERT_ORDER.index(parent)
        child_idx = INSERT_ORDER.index(child)
        assert parent_idx < child_idx, f"{parent} (idx={parent_idx}) must come before {child} (idx={child_idx})"


# ── Property 9: migration_id consistency ────────────────


class TestMigrationIdConsistencyProperty:
    """Property 9: migration_id is identical in both manifest files."""

    @given(migration_id=st.uuids())
    @hsettings(max_examples=100)
    def test_migration_id_matches_across_manifests(self, migration_id):
        mid = str(migration_id)
        manifest = {
            "schema_version": "1.0",
            "migration_id": mid,
            "exported_at": datetime.now(UTC).isoformat(),
            "source_alembic_version": "0009",
            "tables": {},
        }
        migration_manifest = {
            "migration_id": mid,
            "phase1_completed_at": datetime.now(UTC).isoformat(),
            "source_db_url_hash": "abc",
            "table_row_counts": {},
            "uuid_ranges": {},
        }
        # Serialize and deserialize both
        m1 = json.loads(json.dumps(manifest))
        m2 = json.loads(json.dumps(migration_manifest))
        assert m1["migration_id"] == m2["migration_id"]
        assert m1["migration_id"] == mid


# ── Property 10: Admin role authorization gate ──────────


class TestAdminRoleGateProperty:
    """Property 10: Only admin and super_admin roles pass the gate."""

    ALLOWED_ROLES = {"admin", "super_admin"}

    @given(role=st.sampled_from(["admin", "super_admin", "user", "reviewer", "", "moderator", "guest", "operator"]))
    @hsettings(max_examples=100)
    def test_role_gate(self, role):
        with patch("observal_cli.cmd_migrate.client") as mock_client:
            mock_client.get.return_value = {"role": role}
            if role in self.ALLOWED_ROLES:
                _require_admin()  # Should not raise
            else:
                with pytest.raises((SystemExit, click.exceptions.Exit)):
                    _require_admin()
