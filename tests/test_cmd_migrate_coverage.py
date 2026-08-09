# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Behavioral coverage for the migration CLI boundary."""

from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import typer

import observal_cli.cmd_migrate as migrate
from observal_shared.migration import (
    ChecksumMismatchError,
    ConnectionFailedError,
    MigrationError,
    PrerequisiteError,
)
from observal_shared.migration.results import (
    ChecksumResult,
    ExportResult,
    ImportResult,
    TelemetryExportResult,
    TelemetryImportResult,
    TelemetryValidationResult,
    ValidationResult,
)

_REQUIRE_ADMIN = migrate._require_admin
_REQUIRE_PYARROW = migrate._require_pyarrow


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Capture rendering and isolate authentication, prompts, and spinners."""
    lines: list[str] = []
    spinner_messages: list[str] = []
    admin = MagicMock()
    confirm = MagicMock(side_effect=AssertionError("migration commands must remain noninteractive"))

    @contextmanager
    def fake_spinner(message: str):
        spinner_messages.append(message)
        yield

    monkeypatch.setattr(migrate, "rprint", lambda *values, **_kwargs: lines.append(" ".join(map(str, values))))
    monkeypatch.setattr(migrate, "_require_admin", admin)
    monkeypatch.setattr(migrate, "spinner", fake_spinner)
    monkeypatch.setattr(migrate.typer, "confirm", confirm)

    return SimpleNamespace(
        admin=admin,
        confirm=confirm,
        lines=lines,
        spinner_messages=spinner_messages,
        text=lambda: "\n".join(lines),
    )


def _assert_exit_one(exc: pytest.ExceptionInfo[typer.Exit]) -> None:
    assert exc.value.exit_code == 1


def _export_result(path: Path) -> ExportResult:
    return ExportResult(
        archive_path=str(path),
        migration_id="migration-pg",
        table_counts={"users": 2, "agents": 1},
        checksums={"users": "abc", "agents": "def"},
        duration_seconds=2.25,
        total_rows=3,
    )


def _import_result(*, warnings: list[str] | None = None) -> ImportResult:
    return ImportResult(
        migration_id="migration-pg",
        tables_imported=2,
        rows_inserted={"users": 1, "agents": 2},
        rows_skipped={"users": 3, "agents": 4},
        duration_seconds=3.5,
        warnings=warnings or [],
    )


def _telemetry_export_result(output_dir: Path) -> TelemetryExportResult:
    return TelemetryExportResult(
        output_dir=str(output_dir),
        migration_id="migration-ch",
        table_results={"session_events": {"files": [], "row_count": 2500}},
        total_rows=2500,
        total_size_bytes=1572864,
        duration_seconds=4.75,
    )


def _telemetry_import_result(*, warnings: list[str] | None = None) -> TelemetryImportResult:
    return TelemetryImportResult(
        migration_id="migration-ch",
        tables_imported=2,
        tables_skipped=["audit_log"],
        rows_imported={"session_events": 1200, "security_events": 34},
        duration_seconds=5.25,
        warnings=warnings or [],
    )


def test_progress_reporter_renders_phase_boundaries(cli):
    reporter = migrate.RichProgressReporter()

    asyncio.run(reporter.update(phase="connect", pct=1, message="Connecting"))
    asyncio.run(reporter.update(phase="connect", pct=25, message="Reading"))
    asyncio.run(reporter.update(phase="write", pct=100, message="Complete"))

    assert cli.lines == [
        "  [dim][  1%][/dim] Connecting",
        "  [dim][ 25%][/dim] Reading",
        "",
        "  [dim][100%][/dim] Complete",
    ]


def test_admin_gate_allows_super_admin_and_uses_whoami(monkeypatch, cli):
    get = MagicMock(return_value={"role": "super_admin"})
    monkeypatch.setattr(migrate.client, "get", get)
    monkeypatch.setattr(migrate, "_require_admin", _REQUIRE_ADMIN)

    migrate._require_admin()

    get.assert_called_once_with("/api/v1/auth/whoami")
    assert cli.lines == []


def test_admin_gate_reports_authentication_failure(monkeypatch, cli):
    failure = SystemExit(7)
    monkeypatch.setattr(migrate.client, "get", MagicMock(side_effect=failure))
    monkeypatch.setattr(migrate, "_require_admin", _REQUIRE_ADMIN)

    with pytest.raises(typer.Exit) as exc:
        migrate._require_admin()

    _assert_exit_one(exc)
    assert exc.value.__cause__ is failure
    assert "Authentication required" in cli.text()
    assert "observal auth login" in cli.text()


def test_admin_gate_escapes_untrusted_role_markup(monkeypatch, cli):
    monkeypatch.setattr(migrate.client, "get", MagicMock(return_value={"role": "[/]operator"}))
    monkeypatch.setattr(migrate, "_require_admin", _REQUIRE_ADMIN)

    with pytest.raises(typer.Exit) as exc:
        migrate._require_admin()

    _assert_exit_one(exc)
    assert "Permission denied" in cli.text()
    assert "\\[/]operator" in cli.text()


def test_pyarrow_dependency_guard_and_callback(monkeypatch):
    require = MagicMock()
    monkeypatch.setattr(migrate, "_require_pyarrow", require)
    migrate._migrate_callback()
    require.assert_called_once_with()

    monkeypatch.setattr(migrate, "_require_pyarrow", _REQUIRE_PYARROW)
    with monkeypatch.context() as missing:
        missing.setitem(sys.modules, "pyarrow", None)
        with pytest.raises(typer.BadParameter, match=r"observal-cli\[migrate\]") as exc:
            migrate._require_pyarrow()
    assert isinstance(exc.value.__cause__, ImportError)

    with monkeypatch.context() as installed:
        installed.setitem(sys.modules, "pyarrow", SimpleNamespace())
        migrate._require_pyarrow()


@pytest.mark.parametrize(
    ("error", "heading", "detail"),
    [
        (ChecksumMismatchError("checksum differs"), "Checksum verification failed", "corrupted or tampered"),
        (ConnectionFailedError("database unavailable"), "Connection failed", None),
        (PrerequisiteError("manifest missing"), "Prerequisite not met", None),
        (MigrationError("migration stopped"), "Migration error", None),
    ],
)
def test_migration_errors_render_safe_specific_messages(cli, error, heading, detail):
    with pytest.raises(typer.Exit) as exc:
        migrate._handle_migration_error(error)

    _assert_exit_one(exc)
    assert heading in cli.text()
    assert str(error) in cli.text()
    if detail:
        assert detail in cli.text()


def test_clickhouse_cleartext_warning_only_when_credentials_are_exposed(cli):
    migrate._warn_clickhouse_cleartext("clickhouse://operator:sensitive@db.example/observal")
    assert "unencrypted HTTP" in cli.text()
    assert "sensitive" not in cli.text()

    cli.lines.clear()
    migrate._warn_clickhouse_cleartext("clickhouses://operator:sensitive@db.example/observal")
    migrate._warn_clickhouse_cleartext("clickhouse://db.example/observal")
    assert cli.lines == []


def test_export_delegates_connection_path_progress_and_renders_summary(tmp_path, monkeypatch, cli):
    output = tmp_path / "nested" / "snapshot.tar.gz"

    async def export(params, path, reporter):
        assert params.dsn == "postgresql://source.example/observal"
        assert path == output
        await reporter.update(phase="export", pct=50, message="Writing users")
        path.write_bytes(b"x" * 1048576)
        return _export_result(path)

    export_pg = AsyncMock(side_effect=export)
    monkeypatch.setattr(migrate, "export_pg", export_pg)

    migrate.export_cmd("postgresql://source.example/observal", str(output))

    cli.admin.assert_called_once_with()
    cli.confirm.assert_not_called()
    assert cli.spinner_messages == ["Connecting to source database..."]
    assert output.parent.is_dir()
    assert export_pg.await_count == 1
    assert "[ 50%]" in cli.text()
    assert "Export complete" in cli.text()
    assert "migration-pg" in cli.text()
    assert "Tables:     2" in cli.text()
    assert "Rows:       3" in cli.text()
    assert "Size:       1.0 MB" in cli.text()
    assert "Duration:   2.2s" in cli.text()
    assert "hashed credentials" in cli.text()


def test_export_builds_deterministic_default_name(tmp_path, monkeypatch, cli):
    class FrozenDateTime:
        @classmethod
        def now(cls, timezone):
            assert timezone is UTC
            return datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)

    async def export(_params, path, _reporter):
        path.write_bytes(b"archive")
        return _export_result(path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(migrate, "datetime", FrozenDateTime)
    export_pg = AsyncMock(side_effect=export)
    monkeypatch.setattr(migrate, "export_pg", export_pg)

    migrate.export_cmd("postgresql://source.example/observal", None)

    path = Path("observal-export-20260203-040506.tar.gz")
    assert export_pg.await_args.args[1] == path
    assert (tmp_path / path).read_bytes() == b"archive"
    assert str(path) in cli.text()


def test_export_rejects_existing_output_before_connecting(tmp_path, monkeypatch, cli):
    output = tmp_path / "existing.tar.gz"
    output.write_bytes(b"keep")
    export_pg = AsyncMock()
    monkeypatch.setattr(migrate, "export_pg", export_pg)

    with pytest.raises(typer.Exit) as exc:
        migrate.export_cmd("postgresql://source.example/observal", str(output))

    _assert_exit_one(exc)
    export_pg.assert_not_awaited()
    assert output.read_bytes() == b"keep"
    assert "already exists" in cli.text()
    assert "different path" in cli.text()


def test_export_surfaces_parent_creation_failure(tmp_path, monkeypatch, cli):
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("occupied", encoding="utf-8")
    export_pg = AsyncMock()
    monkeypatch.setattr(migrate, "export_pg", export_pg)

    with pytest.raises(typer.Exit) as exc:
        migrate.export_cmd("postgresql://source.example/observal", str(parent_file / "archive.tar.gz"))

    _assert_exit_one(exc)
    export_pg.assert_not_awaited()
    assert "Cannot create output directory" in cli.text()
    assert str(parent_file) in cli.text()


def test_import_validates_archive_delegates_and_renders_accounting(tmp_path, monkeypatch, cli):
    archive = tmp_path / "snapshot.tar.gz"
    archive.touch()
    is_tarfile = MagicMock(return_value=True)
    import_pg = AsyncMock(return_value=_import_result(warnings=["one table used a default"]))
    monkeypatch.setattr(migrate.tarfile, "is_tarfile", is_tarfile)
    monkeypatch.setattr(migrate, "import_pg", import_pg)

    migrate.import_cmd("postgresql://target.example/observal", str(archive))

    is_tarfile.assert_called_once_with(archive)
    params, delegated_archive, reporter = import_pg.await_args.args
    assert params.dsn == "postgresql://target.example/observal"
    assert delegated_archive == archive
    assert isinstance(reporter, migrate.RichProgressReporter)
    assert cli.spinner_messages == ["Importing..."]
    assert "Import complete" in cli.text()
    assert "Inserted:   3" in cli.text()
    assert "Skipped:    7" in cli.text()
    assert "one table used a default" in cli.text()


@pytest.mark.parametrize("command", [migrate.import_cmd, migrate.validate_cmd])
def test_postgres_archive_commands_reject_missing_files(command, tmp_path, monkeypatch, cli):
    is_tarfile = MagicMock()
    monkeypatch.setattr(migrate.tarfile, "is_tarfile", is_tarfile)
    missing = tmp_path / "missing.tar.gz"

    with pytest.raises(typer.Exit) as exc:
        if command is migrate.import_cmd:
            command("postgresql://target.example/observal", str(missing))
        else:
            command(str(missing), None)

    _assert_exit_one(exc)
    is_tarfile.assert_not_called()
    assert "Archive not found" in cli.text()


@pytest.mark.parametrize("command", [migrate.import_cmd, migrate.validate_cmd])
def test_postgres_archive_commands_reject_invalid_tar_files(command, tmp_path, monkeypatch, cli):
    archive = tmp_path / "invalid.tar.gz"
    archive.write_bytes(b"not an archive")
    monkeypatch.setattr(migrate.tarfile, "is_tarfile", MagicMock(return_value=False))

    with pytest.raises(typer.Exit) as exc:
        if command is migrate.import_cmd:
            command("postgresql://target.example/observal", str(archive))
        else:
            command(str(archive), None)

    _assert_exit_one(exc)
    assert "Invalid archive format" in cli.text()
    if command is migrate.import_cmd:
        assert "Expected a .tar.gz file" in cli.text()


def test_validate_renders_checksum_and_database_comparison(tmp_path, monkeypatch, cli):
    archive = tmp_path / "snapshot.tar.gz"
    archive.touch()
    result = ValidationResult(
        archive_valid=True,
        checksum_results=[ChecksumResult("users", "abc", "abc", True)],
        cross_db_results={"missing": (1, -1), "same": (2, 2), "changed": (3, 4)},
    )
    validate_pg = AsyncMock(return_value=result)
    monkeypatch.setattr(migrate.tarfile, "is_tarfile", MagicMock(return_value=True))
    monkeypatch.setattr(migrate, "validate_pg", validate_pg)

    migrate.validate_cmd(str(archive), "postgresql://target.example/observal")

    params, delegated_archive, reporter = validate_pg.await_args.args
    assert params.dsn == "postgresql://target.example/observal"
    assert delegated_archive == archive
    assert isinstance(reporter, migrate.RichProgressReporter)
    assert "Checksum verification" in cli.text()
    assert "All checksums valid" in cli.text()
    assert "table not in database" in cli.text()
    assert "same: 2" in cli.text()
    assert "archive=3, db=4" in cli.text()
    assert "1 table(s) have different row counts" in cli.text()


def test_validate_without_database_reports_all_matching_counts(tmp_path, monkeypatch, cli):
    archive = tmp_path / "snapshot.tar.gz"
    archive.touch()
    validate_pg = AsyncMock(
        return_value=ValidationResult(
            archive_valid=True,
            checksum_results=[],
            cross_db_results={"users": (5, 5)},
        )
    )
    monkeypatch.setattr(migrate.tarfile, "is_tarfile", MagicMock(return_value=True))
    monkeypatch.setattr(migrate, "validate_pg", validate_pg)

    migrate.validate_cmd(str(archive), None)

    assert validate_pg.await_args.args[0] is None
    assert "All row counts match" in cli.text()


def test_validate_exits_when_service_marks_archive_invalid(tmp_path, monkeypatch, cli):
    archive = tmp_path / "snapshot.tar.gz"
    archive.touch()
    validate_pg = AsyncMock(
        return_value=ValidationResult(
            archive_valid=False,
            checksum_results=[ChecksumResult("users", "expected", "actual", False)],
            cross_db_results=None,
        )
    )
    monkeypatch.setattr(migrate.tarfile, "is_tarfile", MagicMock(return_value=True))
    monkeypatch.setattr(migrate, "validate_pg", validate_pg)

    with pytest.raises(typer.Exit) as exc:
        migrate.validate_cmd(str(archive), None)

    _assert_exit_one(exc)
    assert "[red]✗[/red] users" in cli.text()
    assert "Archive validation failed" in cli.text()


def test_telemetry_export_delegates_connections_and_renders_pii_warning(tmp_path, monkeypatch, cli):
    manifest = tmp_path / "migration_manifest.json"
    output_dir = tmp_path / "telemetry"
    export_ch = AsyncMock(return_value=_telemetry_export_result(output_dir))
    warning = MagicMock()
    logger = MagicMock()
    monkeypatch.setattr(migrate, "export_ch", export_ch)
    monkeypatch.setattr(migrate, "_warn_clickhouse_cleartext", warning)
    monkeypatch.setattr(migrate.logging, "getLogger", MagicMock(return_value=logger))

    migrate.export_telemetry_cmd(
        "clickhouses://source.example/observal",
        str(manifest),
        str(output_dir),
    )

    logger.setLevel.assert_called_once_with(migrate.logging.WARNING)
    warning.assert_called_once_with("clickhouses://source.example/observal")
    params, delegated_manifest, delegated_output, reporter = export_ch.await_args.args
    assert params.url == "clickhouses://source.example/observal"
    assert delegated_manifest == manifest
    assert delegated_output == output_dir
    assert isinstance(reporter, migrate.RichProgressReporter)
    assert "Telemetry export complete" in cli.text()
    assert "Rows:       2,500" in cli.text()
    assert "Size:       1.5 MB" in cli.text()
    assert "PII" in cli.text()


def test_telemetry_import_validates_directory_and_renders_resume_outcome(tmp_path, monkeypatch, cli):
    input_dir = tmp_path / "telemetry"
    input_dir.mkdir()
    import_ch = AsyncMock(return_value=_telemetry_import_result(warnings=["partition was already present"]))
    warning = MagicMock()
    logger = MagicMock()
    monkeypatch.setattr(migrate, "import_ch", import_ch)
    monkeypatch.setattr(migrate, "_warn_clickhouse_cleartext", warning)
    monkeypatch.setattr(migrate.logging, "getLogger", MagicMock(return_value=logger))

    migrate.import_telemetry_cmd("clickhouse://target.example/observal", str(input_dir))

    logger.setLevel.assert_called_once_with(migrate.logging.WARNING)
    warning.assert_called_once_with("clickhouse://target.example/observal")
    params, delegated_input, reporter = import_ch.await_args.args
    assert params.url == "clickhouse://target.example/observal"
    assert delegated_input == input_dir
    assert isinstance(reporter, migrate.RichProgressReporter)
    assert "Telemetry import complete" in cli.text()
    assert "Rows:       1,234" in cli.text()
    assert "Skipped:    audit_log" in cli.text()
    assert "partition was already present" in cli.text()


def test_telemetry_commands_reject_missing_input_directories(tmp_path, monkeypatch, cli):
    missing = tmp_path / "missing"
    import_ch = AsyncMock()
    validate_ch = AsyncMock()
    monkeypatch.setattr(migrate, "import_ch", import_ch)
    monkeypatch.setattr(migrate, "validate_ch", validate_ch)

    with pytest.raises(typer.Exit) as import_exc:
        migrate.import_telemetry_cmd("clickhouse://target.example/observal", str(missing))
    with pytest.raises(typer.Exit) as validate_exc:
        migrate.validate_telemetry_cmd(str(missing), None, None)

    _assert_exit_one(import_exc)
    _assert_exit_one(validate_exc)
    import_ch.assert_not_awaited()
    validate_ch.assert_not_awaited()
    assert cli.text().count("Directory not found") == 2


def test_telemetry_validate_renders_checks_counts_and_orphans(tmp_path, monkeypatch, cli):
    input_dir = tmp_path / "telemetry"
    input_dir.mkdir()
    result = TelemetryValidationResult(
        checksums_valid=True,
        checksum_results={"events.parquet": True},
        row_count_results={"missing": (1, -1), "same": (2, 2), "changed": (3000, 2000)},
        fk_results={
            "orphaned_agent_ids": ["agent-id"],
            "orphaned_agent_ids_truncated": True,
            "orphaned_user_ids": [],
            "orphaned_actor_ids": ["actor-id"],
        },
    )
    validate_ch = AsyncMock(return_value=result)
    warning = MagicMock()
    logger = MagicMock()
    monkeypatch.setattr(migrate, "validate_ch", validate_ch)
    monkeypatch.setattr(migrate, "_warn_clickhouse_cleartext", warning)
    monkeypatch.setattr(migrate.logging, "getLogger", MagicMock(return_value=logger))

    migrate.validate_telemetry_cmd(
        str(input_dir),
        "clickhouses://target.example/observal",
        "postgresql://target.example/observal",
    )

    logger.setLevel.assert_called_once_with(migrate.logging.WARNING)
    warning.assert_called_once_with("clickhouses://target.example/observal")
    ch_params, pg_params, delegated_input, reporter = validate_ch.await_args.args
    assert ch_params.url == "clickhouses://target.example/observal"
    assert pg_params.dsn == "postgresql://target.example/observal"
    assert delegated_input == input_dir
    assert isinstance(reporter, migrate.RichProgressReporter)
    assert "events.parquet" in cli.text()
    assert "table not on target" in cli.text()
    assert "same: 2" in cli.text()
    assert "manifest=3,000, db=2,000" in cli.text()
    assert "1 table(s) have different row counts" in cli.text()
    assert "orphaned_agent_ids: 1 orphaned (truncated)" in cli.text()
    assert "orphaned_user_ids: 0 orphaned" in cli.text()
    assert "orphaned_actor_ids: 1 orphaned" in cli.text()
    assert "Orphaned references found" in cli.text()


def test_telemetry_validate_without_connections_reports_clean_results(tmp_path, monkeypatch, cli):
    input_dir = tmp_path / "telemetry"
    input_dir.mkdir()
    validate_ch = AsyncMock(
        return_value=TelemetryValidationResult(
            checksums_valid=True,
            checksum_results={},
            row_count_results={"session_events": (10, 10)},
            fk_results={"orphaned_agent_ids": []},
        )
    )
    warning = MagicMock()
    monkeypatch.setattr(migrate, "validate_ch", validate_ch)
    monkeypatch.setattr(migrate, "_warn_clickhouse_cleartext", warning)

    migrate.validate_telemetry_cmd(str(input_dir), None, None)

    assert validate_ch.await_args.args[:2] == (None, None)
    warning.assert_not_called()
    assert "All row counts match" in cli.text()
    assert "All FK references valid" in cli.text()


def test_telemetry_validate_exits_on_bad_checksum(tmp_path, monkeypatch, cli):
    input_dir = tmp_path / "telemetry"
    input_dir.mkdir()
    validate_ch = AsyncMock(
        return_value=TelemetryValidationResult(
            checksums_valid=False,
            checksum_results={"corrupt.parquet": False},
            row_count_results=None,
            fk_results=None,
        )
    )
    monkeypatch.setattr(migrate, "validate_ch", validate_ch)

    with pytest.raises(typer.Exit) as exc:
        migrate.validate_telemetry_cmd(str(input_dir), None, None)

    _assert_exit_one(exc)
    assert "[red]✗[/red] corrupt.parquet" in cli.text()
    assert "Checksum validation failed" in cli.text()


def test_every_command_translates_service_failures_to_exit_one(tmp_path, monkeypatch, cli):
    archive = tmp_path / "snapshot.tar.gz"
    archive.touch()
    input_dir = tmp_path / "telemetry"
    input_dir.mkdir()
    monkeypatch.setattr(migrate.tarfile, "is_tarfile", MagicMock(return_value=True))

    services = {
        "export_pg": AsyncMock(side_effect=MigrationError("safe service failure")),
        "import_pg": AsyncMock(side_effect=MigrationError("safe service failure")),
        "validate_pg": AsyncMock(side_effect=MigrationError("safe service failure")),
        "export_ch": AsyncMock(side_effect=MigrationError("safe service failure")),
        "import_ch": AsyncMock(side_effect=MigrationError("safe service failure")),
        "validate_ch": AsyncMock(side_effect=MigrationError("safe service failure")),
    }
    for name, service in services.items():
        monkeypatch.setattr(migrate, name, service)

    commands = [
        lambda: migrate.export_cmd("postgresql://source.example/observal", str(tmp_path / "failed.tar.gz")),
        lambda: migrate.import_cmd("postgresql://target.example/observal", str(archive)),
        lambda: migrate.validate_cmd(str(archive), None),
        lambda: migrate.export_telemetry_cmd(
            "clickhouses://source.example/observal",
            str(tmp_path / "manifest.json"),
            str(tmp_path / "output"),
        ),
        lambda: migrate.import_telemetry_cmd("clickhouses://target.example/observal", str(input_dir)),
        lambda: migrate.validate_telemetry_cmd(str(input_dir), None, None),
    ]

    for command in commands:
        with pytest.raises(typer.Exit) as exc:
            command()
        _assert_exit_one(exc)

    assert all(service.await_count == 1 for service in services.values())
    assert cli.text().count("Migration error") == 6


def test_connection_credentials_are_only_delegated_never_rendered(tmp_path, monkeypatch, cli):
    output = tmp_path / "failed.tar.gz"
    database_url = "postgresql://operator:sensitive-value@source.example/observal"
    export_pg = AsyncMock(side_effect=ConnectionFailedError("connection refused"))
    monkeypatch.setattr(migrate, "export_pg", export_pg)

    with pytest.raises(typer.Exit):
        migrate.export_cmd(database_url, str(output))

    assert export_pg.await_args.args[0].dsn == database_url
    assert database_url not in cli.text()
    assert "sensitive-value" not in cli.text()
    assert "Connection failed" in cli.text()
