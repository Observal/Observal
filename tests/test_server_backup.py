# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for observal_cli.server.backup."""

from __future__ import annotations

import pytest

from observal_cli.server import backup


@pytest.fixture(autouse=True)
def isolated_backups(tmp_path, monkeypatch):
    """Redirect backup directory to tmp."""
    monkeypatch.setattr(backup, "BACKUPS_DIR", tmp_path / "backups")
    return tmp_path / "backups"


class TestListBackups:
    def test_empty_dir(self, isolated_backups):
        assert backup.list_backups() == []

    def test_lists_existing_backups(self, isolated_backups):
        # Create fake backup dirs
        b1 = isolated_backups / "v0.7.0-20260521T120000"
        b1.mkdir(parents=True)
        (b1 / "pg.dump").write_bytes(b"fake pg dump data" * 100)
        (b1 / "analytics.tar.gz").write_bytes(b"fake analytics archive")

        b2 = isolated_backups / "v0.6.0-20260501T100000"
        b2.mkdir(parents=True)
        (b2 / "pg.dump").write_bytes(b"older dump")

        results = backup.list_backups()
        assert len(results) == 2
        assert results[0]["name"] == "v0.7.0-20260521T120000"  # Most recent first
        assert results[0]["has_pg"] is True
        assert results[0]["has_analytics"] is True
        assert results[1]["has_analytics"] is False


class TestPruneBackups:
    def test_prune_beyond_retention(self, isolated_backups):
        # Create 5 backups
        for i in range(5):
            d = isolated_backups / f"v0.{i}.0-2026050{i}T100000"
            d.mkdir(parents=True)
            (d / "pg.dump").write_bytes(b"data")

        pruned = backup.prune_backups(retention=3)
        assert len(pruned) == 2
        remaining = backup.list_backups()
        assert len(remaining) == 3

    def test_no_prune_under_retention(self, isolated_backups):
        for i in range(2):
            d = isolated_backups / f"v0.{i}.0-2026050{i}T100000"
            d.mkdir(parents=True)
            (d / "pg.dump").write_bytes(b"data")

        pruned = backup.prune_backups(retention=3)
        assert pruned == []


class TestEstimateBackupSize:
    def test_fallback_on_failure(self, tmp_path):
        """If docker exec fails, returns 100MB fallback."""
        size = backup.estimate_backup_size(tmp_path)
        # Docker isn't running in tests, so it should return fallback
        assert size == 100 * 1024 * 1024


class TestCreateBackupSafety:
    @pytest.mark.parametrize("stop_failure", ["timeout", "nonzero"])
    def test_restart_is_attempted_when_stop_does_not_succeed(self, tmp_path, monkeypatch, stop_failure):
        from subprocess import TimeoutExpired
        from types import SimpleNamespace

        calls: list[list[str]] = []

        def run(command, **_kwargs):
            calls.append(command)
            if "pg_dump" in command:
                return SimpleNamespace(returncode=0, stdout=b"valid pg dump" * 20, stderr=b"")
            if command[:4] == ["docker", "compose", "exec", "-T"]:
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            if command[2:4] == ["stop", "observal-duckdb"]:
                if stop_failure == "timeout":
                    raise TimeoutExpired(command, 300)
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"stop failed")
            if command[2:5] == ["up", "-d", "observal-duckdb"]:
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            raise AssertionError(f"unexpected command: {command}")

        monkeypatch.setattr(backup.subprocess, "run", run)

        created = backup.create_backup(tmp_path, "1.0.0")

        assert created.exists()
        assert ["docker", "compose", "up", "-d", "observal-duckdb"] in calls
        assert not (created / "analytics.tar.gz").exists()


class TestRestoreBackup:
    """A restore has to bring back both stores, not just PostgreSQL."""

    def _pg_restore_result(self):
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stderr = b""
        return result

    def test_restores_analytics_when_archive_present(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        backup_dir = tmp_path / "v1.13.1-20260917T000000"
        backup_dir.mkdir()
        (backup_dir / "pg.dump").write_bytes(b"pg dump" * 50)
        (backup_dir / "analytics.tar.gz").write_bytes(b"analytics archive")

        analytics_restore = MagicMock()
        monkeypatch.setattr(backup, "_restore_analytics", analytics_restore)
        monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: self._pg_restore_result())

        restored = backup.restore_backup(backup_dir, tmp_path)

        assert restored is True
        analytics_restore.assert_called_once_with(backup_dir / "analytics.tar.gz", tmp_path)

    def test_skips_analytics_when_archive_is_missing(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        backup_dir = tmp_path / "v1.0.0-20260101T000000"
        backup_dir.mkdir()
        (backup_dir / "pg.dump").write_bytes(b"pg dump" * 50)

        analytics_restore = MagicMock()
        monkeypatch.setattr(backup, "_restore_analytics", analytics_restore)
        monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: self._pg_restore_result())

        restored = backup.restore_backup(backup_dir, tmp_path)

        assert restored is False
        analytics_restore.assert_not_called()


class TestAnalyticsRestoreSafety:
    @staticmethod
    def _archive(path):
        import io
        import tarfile

        with tarfile.open(path, "w:gz") as bundle:
            payload = b"duckdb"
            member = tarfile.TarInfo("./analytics.duckdb")
            member.size = len(payload)
            bundle.addfile(member, io.BytesIO(payload))

    def test_rejects_corrupt_archive_before_stopping_service(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        archive = tmp_path / "analytics.tar.gz"
        archive.write_bytes(b"truncated")
        run = MagicMock()
        monkeypatch.setattr(backup.subprocess, "run", run)

        with pytest.raises(RuntimeError, match="archive is invalid"):
            backup._restore_analytics(archive, tmp_path)

        run.assert_not_called()

    def test_aborts_when_writer_cannot_be_stopped(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        archive = tmp_path / "analytics.tar.gz"
        self._archive(archive)
        run = MagicMock(return_value=SimpleNamespace(returncode=1, stderr=b"busy"))
        monkeypatch.setattr(backup.subprocess, "run", run)

        with pytest.raises(RuntimeError, match="could not stop"):
            backup._restore_analytics(archive, tmp_path)

        assert run.call_count == 1

    def test_extracts_to_staging_before_replacing_live_data(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        archive = tmp_path / "analytics.tar.gz"
        self._archive(archive)
        run = MagicMock(return_value=SimpleNamespace(returncode=0, stderr=b""))
        monkeypatch.setattr(backup.subprocess, "run", run)
        monkeypatch.setattr(backup, "_wait_for_service_healthy", MagicMock(return_value=True))

        backup._restore_analytics(archive, tmp_path)

        restore_command = run.call_args_list[1].args[0]
        shell_script = restore_command[-1]
        assert "tar xzf - -C /data/.restore" in shell_script
        assert shell_script.index("tar xzf") < shell_script.index("find /data")
