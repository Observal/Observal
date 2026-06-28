# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests verifying CLI migrate commands invoke the shared Migration_Service correctly.

These tests mock the observal_shared.migration entry points and assert that the CLI
passes the correct arguments (PgConnParams, ChConnParams, paths, options) to
the shared core. No real database connections are made.

Requirements: 8.2, 8.3
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from observal_cli.cmd_migrate import migrate_app

runner = CliRunner()


# ── Helpers ────────────────────────────────────────────────────


def _make_export_result():
    """Build a mock ExportResult."""
    from observal_shared.migration.results import ExportResult

    return ExportResult(
        archive_path="/tmp/test.tar.gz",
        migration_id="mig-123",
        table_counts={"users": 10, "agents": 5},
        checksums={"users": "abc", "agents": "def"},
        duration_seconds=2.5,
        total_rows=15,
    )


def _make_import_result():
    """Build a mock ImportResult."""
    from observal_shared.migration.results import ImportResult

    return ImportResult(
        migration_id="mig-123",
        tables_imported=2,
        rows_inserted={"users": 10, "agents": 5},
        rows_skipped={"users": 0, "agents": 2},
        duration_seconds=3.0,
        warnings=[],
    )


def _make_validation_result():
    """Build a mock ValidationResult."""
    from observal_shared.migration.results import ChecksumResult, ValidationResult

    return ValidationResult(
        archive_valid=True,
        checksum_results=[ChecksumResult("users", "abc", "abc", True)],
        cross_db_results=None,
    )


def _make_telemetry_export_result():
    """Build a mock TelemetryExportResult."""
    from observal_shared.migration.results import TelemetryExportResult

    return TelemetryExportResult(
        output_dir="/tmp/telemetry",
        migration_id="mig-456",
        table_results={"traces": {"files": [], "row_count": 100}},
        total_rows=100,
        total_size_bytes=1024 * 1024,
        duration_seconds=5.0,
    )


def _make_telemetry_import_result():
    """Build a mock TelemetryImportResult."""
    from observal_shared.migration.results import TelemetryImportResult

    return TelemetryImportResult(
        migration_id="mig-456",
        tables_imported=3,
        tables_skipped=[],
        rows_imported={"traces": 100, "spans": 200},
        duration_seconds=4.0,
        warnings=[],
    )


def _make_telemetry_validation_result():
    """Build a mock TelemetryValidationResult."""
    from observal_shared.migration.results import TelemetryValidationResult

    return TelemetryValidationResult(
        checksums_valid=True,
        checksum_results={"traces_2026-01.parquet": True},
        fk_results=None,
        row_count_results=None,
    )


# ── Export command tests ─────────────────────────────────────


class TestExportCommand:
    """Verify export_cmd passes correct args to export_pg."""

    @patch("observal_cli.cmd_migrate.export_pg", new_callable=AsyncMock)
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_export_passes_pg_conn_params(self, mock_admin, mock_export_pg, tmp_path):
        """export_pg receives PgConnParams with the --db-url DSN."""
        mock_export_pg.return_value = _make_export_result()
        output = tmp_path / "out.tar.gz"

        # The CLI checks output_path.stat().st_size after export_pg returns,
        # so we need the file to exist. Create it as a side effect of the mock.
        async def _fake_export(*args, **kwargs):
            output.write_bytes(b"\x00" * 1024)
            return _make_export_result()

        mock_export_pg.side_effect = _fake_export

        result = runner.invoke(
            migrate_app,
            ["export", "--db-url", "postgresql://user:pass@myhost:5432/mydb", "--output", str(output)],
        )

        assert result.exit_code == 0, result.output
        mock_export_pg.assert_called_once()
        args = mock_export_pg.call_args
        # First arg: PgConnParams
        pg_params = args[0][0]
        assert pg_params.dsn == "postgresql://user:pass@myhost:5432/mydb"
        # Second arg: output path
        assert args[0][1] == output
        # Third arg: reporter (RichProgressReporter instance)
        assert hasattr(args[0][2], "update")


# ── Import command tests ─────────────────────────────────────


class TestImportCommand:
    """Verify import_cmd passes correct args to import_pg."""

    @patch("observal_cli.cmd_migrate.import_pg", new_callable=AsyncMock)
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_import_passes_pg_conn_params_and_archive(self, mock_admin, mock_import_pg, tmp_path):
        """import_pg receives PgConnParams, archive path, and org_id."""
        mock_import_pg.return_value = _make_import_result()

        # Create a dummy tar.gz file
        archive = tmp_path / "test.tar.gz"
        import tarfile

        with tarfile.open(archive, "w:gz"):
            pass  # empty tarball

        result = runner.invoke(
            migrate_app,
            [
                "import",
                "--db-url",
                "postgresql://u:p@host/db",
                "--archive",
                str(archive),
                "--org-id",
                "550e8400-e29b-41d4-a716-446655440000",
            ],
        )

        assert result.exit_code == 0, result.output
        mock_import_pg.assert_called_once()
        args, kwargs = mock_import_pg.call_args
        # First arg: PgConnParams
        assert args[0].dsn == "postgresql://u:p@host/db"
        # Second arg: archive path
        assert args[1] == archive
        # Third arg: reporter
        assert hasattr(args[2], "update")
        # Keyword: normalize_org_id
        assert kwargs["normalize_org_id"] == "550e8400-e29b-41d4-a716-446655440000"

    @patch("observal_cli.cmd_migrate.import_pg", new_callable=AsyncMock)
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_import_without_org_id(self, mock_admin, mock_import_pg, tmp_path):
        """Without --org-id, normalize_org_id should be None."""
        mock_import_pg.return_value = _make_import_result()

        archive = tmp_path / "test.tar.gz"
        import tarfile

        with tarfile.open(archive, "w:gz"):
            pass

        result = runner.invoke(
            migrate_app,
            ["import", "--db-url", "postgresql://u:p@h/d", "--archive", str(archive)],
        )

        assert result.exit_code == 0, result.output
        _, kwargs = mock_import_pg.call_args
        assert kwargs["normalize_org_id"] is None


# ── Validate command tests ───────────────────────────────────


class TestValidateCommand:
    """Verify validate_cmd passes correct args to validate_pg."""

    @patch("observal_cli.cmd_migrate.validate_pg", new_callable=AsyncMock)
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_validate_without_db_url(self, mock_admin, mock_validate_pg, tmp_path):
        """validate_pg receives None for pg_params when no --db-url is given."""
        mock_validate_pg.return_value = _make_validation_result()

        archive = tmp_path / "test.tar.gz"
        import tarfile

        with tarfile.open(archive, "w:gz"):
            pass

        result = runner.invoke(
            migrate_app,
            ["validate", "--archive", str(archive)],
        )

        assert result.exit_code == 0, result.output
        mock_validate_pg.assert_called_once()
        args = mock_validate_pg.call_args[0]
        # First arg: pg_params (None when no --db-url)
        assert args[0] is None
        # Second arg: archive path
        assert args[1] == archive

    @patch("observal_cli.cmd_migrate.validate_pg", new_callable=AsyncMock)
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_validate_with_db_url(self, mock_admin, mock_validate_pg, tmp_path):
        """validate_pg receives PgConnParams when --db-url is given."""
        mock_validate_pg.return_value = _make_validation_result()

        archive = tmp_path / "test.tar.gz"
        import tarfile

        with tarfile.open(archive, "w:gz"):
            pass

        result = runner.invoke(
            migrate_app,
            ["validate", "--archive", str(archive), "--db-url", "postgresql://u:p@h/d"],
        )

        assert result.exit_code == 0, result.output
        args = mock_validate_pg.call_args[0]
        assert args[0].dsn == "postgresql://u:p@h/d"


# ── Export telemetry command tests ───────────────────────────


class TestExportTelemetryCommand:
    """Verify export-telemetry passes correct args to export_ch."""

    @patch("observal_cli.cmd_migrate.export_ch", new_callable=AsyncMock)
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_export_telemetry_passes_ch_params(self, mock_admin, mock_export_ch, tmp_path):
        """export_ch receives ChConnParams, manifest path, output dir, and reporter."""
        mock_export_ch.return_value = _make_telemetry_export_result()

        manifest = tmp_path / "manifest.json"
        manifest.write_text("{}")
        output_dir = tmp_path / "out"

        result = runner.invoke(
            migrate_app,
            [
                "export-telemetry",
                "--clickhouse-url",
                "clickhouse://default:pass@localhost:8123/observal",
                "--manifest",
                str(manifest),
                "--output-dir",
                str(output_dir),
            ],
        )

        assert result.exit_code == 0, result.output
        mock_export_ch.assert_called_once()
        args = mock_export_ch.call_args[0]
        # First arg: ChConnParams
        assert args[0].url == "clickhouse://default:pass@localhost:8123/observal"
        # Second arg: manifest path
        assert args[1] == Path(str(manifest))
        # Third arg: output dir
        assert args[2] == Path(str(output_dir))
        # Fourth arg: reporter
        assert hasattr(args[3], "update")


# ── Import telemetry command tests ───────────────────────────


class TestImportTelemetryCommand:
    """Verify import-telemetry passes correct args to import_ch."""

    @patch("observal_cli.cmd_migrate.import_ch", new_callable=AsyncMock)
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_import_telemetry_passes_ch_params_and_project_id(self, mock_admin, mock_import_ch, tmp_path):
        """import_ch receives ChConnParams, input dir, reporter, and project_id."""
        mock_import_ch.return_value = _make_telemetry_import_result()

        input_dir = tmp_path / "telemetry"
        input_dir.mkdir()

        result = runner.invoke(
            migrate_app,
            [
                "import-telemetry",
                "--clickhouse-url",
                "clickhouse://default:@localhost:8123/observal",
                "--input-dir",
                str(input_dir),
                "--project-id",
                "new-project-uuid",
            ],
        )

        assert result.exit_code == 0, result.output
        mock_import_ch.assert_called_once()
        args, kwargs = mock_import_ch.call_args
        # First arg: ChConnParams
        assert args[0].url == "clickhouse://default:@localhost:8123/observal"
        # Second arg: input dir
        assert args[1] == input_dir
        # Third arg: reporter
        assert hasattr(args[2], "update")
        # Keyword: normalize_project_id
        assert kwargs["normalize_project_id"] == "new-project-uuid"

    @patch("observal_cli.cmd_migrate.import_ch", new_callable=AsyncMock)
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_import_telemetry_without_project_id(self, mock_admin, mock_import_ch, tmp_path):
        """Without --project-id, normalize_project_id should be None."""
        mock_import_ch.return_value = _make_telemetry_import_result()

        input_dir = tmp_path / "telemetry"
        input_dir.mkdir()

        result = runner.invoke(
            migrate_app,
            [
                "import-telemetry",
                "--clickhouse-url",
                "clickhouse://default:@localhost:8123/observal",
                "--input-dir",
                str(input_dir),
            ],
        )

        assert result.exit_code == 0, result.output
        _, kwargs = mock_import_ch.call_args
        assert kwargs["normalize_project_id"] is None


# ── Validate telemetry command tests ─────────────────────────


class TestValidateTelemetryCommand:
    """Verify validate-telemetry passes correct args to validate_ch."""

    @patch("observal_cli.cmd_migrate.validate_ch", new_callable=AsyncMock)
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_validate_telemetry_with_all_options(self, mock_admin, mock_validate_ch, tmp_path):
        """validate_ch receives ch_params, pg_params, input dir, and reporter."""
        mock_validate_ch.return_value = _make_telemetry_validation_result()

        input_dir = tmp_path / "telemetry"
        input_dir.mkdir()

        result = runner.invoke(
            migrate_app,
            [
                "validate-telemetry",
                "--input-dir",
                str(input_dir),
                "--clickhouse-url",
                "clickhouse://default:@localhost:8123/observal",
                "--target-db-url",
                "postgresql://u:p@h/d",
            ],
        )

        assert result.exit_code == 0, result.output
        mock_validate_ch.assert_called_once()
        args = mock_validate_ch.call_args[0]
        # First arg: ChConnParams
        assert args[0].url == "clickhouse://default:@localhost:8123/observal"
        # Second arg: PgConnParams
        assert args[1].dsn == "postgresql://u:p@h/d"
        # Third arg: input dir
        assert args[2] == input_dir
        # Fourth arg: reporter
        assert hasattr(args[3], "update")

    @patch("observal_cli.cmd_migrate.validate_ch", new_callable=AsyncMock)
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_validate_telemetry_without_optional_urls(self, mock_admin, mock_validate_ch, tmp_path):
        """Without optional URLs, ch_params and pg_params should be None."""
        mock_validate_ch.return_value = _make_telemetry_validation_result()

        input_dir = tmp_path / "telemetry"
        input_dir.mkdir()

        result = runner.invoke(
            migrate_app,
            ["validate-telemetry", "--input-dir", str(input_dir)],
        )

        assert result.exit_code == 0, result.output
        args = mock_validate_ch.call_args[0]
        assert args[0] is None  # No ch_params
        assert args[1] is None  # No pg_params


# ── Error handling tests ─────────────────────────────────────


class TestErrorHandling:
    """Verify MigrationError is caught and converted to typer.Exit(1)."""

    @patch("observal_cli.cmd_migrate.export_pg", new_callable=AsyncMock)
    @patch("observal_cli.cmd_migrate._require_admin")
    def test_migration_error_causes_exit_1(self, mock_admin, mock_export_pg, tmp_path):
        """A MigrationError from the service should result in exit code 1."""
        from observal_shared.migration.exceptions import ConnectionFailedError

        mock_export_pg.side_effect = ConnectionFailedError("Connection refused")
        output = tmp_path / "out.tar.gz"

        result = runner.invoke(
            migrate_app,
            ["export", "--db-url", "postgresql://u:p@h/d", "--output", str(output)],
        )

        assert result.exit_code == 1
        assert "Connection failed" in result.output
