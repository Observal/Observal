# SPDX-FileCopyrightText: 2026 amogh-dongre <amoghdongre16@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for observal_cli.pi_extension: the npm/local install state machine."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from observal_cli import pi_extension

if TYPE_CHECKING:
    from pathlib import Path

# Fixed regardless of what observal-cli version this test environment actually
# resolves (which varies across invocation contexts) - keeps stale/current/newer
# comparisons deterministic.
CLI_VERSION = "2.0.0"


@pytest.fixture(autouse=True)
def fixed_cli_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pi_extension, "get_current_version", lambda: CLI_VERSION)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_legacy_install(tmp_path: Path) -> Path:
    """An observal.ts an older CLI wrote: our header, older body, no manifest."""
    extension = pi_extension.extension_path(tmp_path)
    extension.parent.mkdir(parents=True, exist_ok=True)
    extension.write_text(
        f"/**\n * {pi_extension._SIGNATURE}\n */\nconst old = true;\n",
        encoding="utf-8",
    )
    return extension


class TestCheckStatus:
    def test_not_detected_when_pi_agent_dir_is_missing(self, tmp_path: Path):
        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.NOT_DETECTED
        assert status.action is None

    def test_not_installed_when_pi_present_and_extension_absent(self, tmp_path: Path):
        (tmp_path / ".pi/agent").mkdir(parents=True)

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.NOT_INSTALLED
        assert status.action == "install"

    def test_npm_string_entry_pinned_and_current_skips_local(self, tmp_path: Path):
        write_json(
            tmp_path / ".pi/agent/settings.json",
            {"packages": [f"npm:observal-pi@{CLI_VERSION}"]},
        )

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.NPM_CURRENT
        assert status.action is None

    def test_npm_dict_entry_is_recognized(self, tmp_path: Path):
        write_json(
            tmp_path / ".pi/agent/settings.json",
            {"packages": [{"source": f"npm:observal-pi@{CLI_VERSION}"}]},
        )

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.NPM_CURRENT

    def test_npm_unpinned_entry_is_not_flagged_stale(self, tmp_path: Path):
        write_json(tmp_path / ".pi/agent/settings.json", {"packages": ["npm:observal-pi"]})

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.NPM_UNPINNED
        assert status.message is None

    def test_npm_pinned_older_than_cli_is_stale(self, tmp_path: Path):
        write_json(tmp_path / ".pi/agent/settings.json", {"packages": ["npm:observal-pi@0.0.1"]})

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.NPM_STALE
        assert "pi update npm:observal-pi" in status.message
        assert status.action is None  # never installs locally, even though stale

    def test_unrelated_npm_packages_do_not_trigger_npm_mode(self, tmp_path: Path):
        (tmp_path / ".pi/agent").mkdir(parents=True)
        write_json(tmp_path / ".pi/agent/settings.json", {"packages": ["npm:@observal/pi-insights"]})

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.NOT_INSTALLED

    def test_local_adopts_pre_manifest_install_when_content_matches(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text(pi_extension.extension_source(), encoding="utf-8")

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.CURRENT
        assert status.action == "adopt"

    def test_local_flags_conflict_when_content_differs_and_no_manifest(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text("someone else's extension", encoding="utf-8")

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.UNMANAGED
        assert status.action is None
        assert "not managed by Observal" in status.message

    def test_bundled_source_carries_the_migration_signature(self):
        # Guards the migration path: if the extension's doc header is ever
        # reworded, pre-manifest installs silently stop being recognized.
        assert pi_extension._SIGNATURE in pi_extension.extension_source()

    def test_pre_manifest_observal_install_is_migratable_not_unmanaged(self, tmp_path: Path):
        write_legacy_install(tmp_path)

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.MIGRATABLE
        assert status.action == "migrate"
        assert "older Observal CLI" in status.message
        assert pi_extension.backup_path(tmp_path).name in status.message

    def test_corrupt_manifest_beside_our_file_is_migratable(self, tmp_path: Path):
        write_legacy_install(tmp_path)
        pi_extension.manifest_path(tmp_path).write_text("{not json", encoding="utf-8")

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.MIGRATABLE

    def test_unparseable_manifest_version_beside_our_file_is_migratable(self, tmp_path: Path):
        write_legacy_install(tmp_path)
        write_json(pi_extension.manifest_path(tmp_path), {"managed": True, "version": "not-a-version"})

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.MIGRATABLE

    def test_npm_mode_still_wins_over_a_migratable_local_file(self, tmp_path: Path):
        write_legacy_install(tmp_path)
        write_json(tmp_path / ".pi/agent/settings.json", {"packages": ["npm:observal-pi"]})

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.NPM_UNPINNED
        assert status.action is None

    def test_local_manifest_stale_reports_both_versions(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text("old", encoding="utf-8")
        write_json(tmp_path / ".pi/agent/extensions/.observal-extension.json", {"managed": True, "version": "0.0.1"})

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.STALE
        assert status.action == "refresh"
        assert "0.0.1" in status.message
        assert CLI_VERSION in status.message

    def test_local_manifest_newer_is_not_downgraded(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text("from the future", encoding="utf-8")
        write_json(tmp_path / ".pi/agent/extensions/.observal-extension.json", {"managed": True, "version": "9999.0.0"})

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.NEWER
        assert status.action is None

    def test_unmanaged_flag_false_in_manifest_is_treated_as_untrusted(self, tmp_path: Path):
        extension = tmp_path / ".pi/agent/extensions/observal.ts"
        extension.parent.mkdir(parents=True)
        extension.write_text("hand written", encoding="utf-8")
        write_json(tmp_path / ".pi/agent/extensions/.observal-extension.json", {"managed": False, "version": "1.0.0"})

        status = pi_extension.check_status(home=tmp_path)

        assert status.state == pi_extension.UNMANAGED

    def test_invalid_settings_json_raises(self, tmp_path: Path):
        settings = tmp_path / ".pi/agent/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text("[]", encoding="utf-8")  # valid JSON, not an object

        with pytest.raises(ValueError):
            pi_extension.check_status(home=tmp_path)


class TestInstallOrRefresh:
    def test_creates_parent_directories_on_first_install(self, tmp_path: Path):
        (tmp_path / ".pi/agent").mkdir(parents=True)

        changed, action = pi_extension.install_or_refresh(dry_run=False, home=tmp_path)

        assert changed is True
        assert action == "install"
        assert pi_extension.extension_path(tmp_path).read_text() == pi_extension.extension_source()
        assert read_json(pi_extension.manifest_path(tmp_path)) == {
            "managed": True,
            "version": CLI_VERSION,
        }

    def test_dry_run_reports_without_writing(self, tmp_path: Path):
        (tmp_path / ".pi/agent").mkdir(parents=True)

        changed, action = pi_extension.install_or_refresh(dry_run=True, home=tmp_path)

        assert changed is True
        assert action == "install"
        assert not pi_extension.extension_path(tmp_path).exists()

    def test_noop_when_npm_is_configured(self, tmp_path: Path):
        write_json(tmp_path / ".pi/agent/settings.json", {"packages": ["npm:observal-pi"]})

        changed, action = pi_extension.install_or_refresh(dry_run=False, home=tmp_path)

        assert (changed, action) == (False, None)
        assert not pi_extension.extension_path(tmp_path).exists()

    def test_noop_when_file_is_unmanaged(self, tmp_path: Path):
        extension = pi_extension.extension_path(tmp_path)
        extension.parent.mkdir(parents=True)
        extension.write_text("do not touch", encoding="utf-8")

        changed, action = pi_extension.install_or_refresh(dry_run=False, home=tmp_path)

        assert (changed, action) == (False, None)
        assert extension.read_text() == "do not touch"

    def test_adopt_writes_manifest_without_changing_extension_bytes(self, tmp_path: Path):
        extension = pi_extension.extension_path(tmp_path)
        extension.parent.mkdir(parents=True)
        source = pi_extension.extension_source()
        extension.write_text(source, encoding="utf-8")

        changed, action = pi_extension.install_or_refresh(dry_run=False, home=tmp_path)

        assert (changed, action) == (True, "adopt")
        assert extension.read_text() == source
        assert read_json(pi_extension.manifest_path(tmp_path))["version"] == CLI_VERSION

    def test_migrate_backs_up_the_previous_file_then_refreshes(self, tmp_path: Path):
        extension = write_legacy_install(tmp_path)
        previous = extension.read_text()
        backup = pi_extension.backup_path(tmp_path)

        changed, action = pi_extension.install_or_refresh(dry_run=False, home=tmp_path)

        assert (changed, action) == (True, "migrate")
        assert extension.read_text() == pi_extension.extension_source()
        assert backup.read_text() == previous
        assert read_json(pi_extension.manifest_path(tmp_path))["version"] == CLI_VERSION

    def test_migrate_dry_run_writes_nothing(self, tmp_path: Path):
        extension = write_legacy_install(tmp_path)
        previous = extension.read_text()

        changed, action = pi_extension.install_or_refresh(dry_run=True, home=tmp_path)

        assert (changed, action) == (True, "migrate")
        assert extension.read_text() == previous
        assert not pi_extension.backup_path(tmp_path).exists()
        assert not pi_extension.manifest_path(tmp_path).exists()

    def test_migrated_install_is_current_afterwards(self, tmp_path: Path):
        write_legacy_install(tmp_path)

        pi_extension.install_or_refresh(dry_run=False, home=tmp_path)

        assert pi_extension.check_status(home=tmp_path).state == pi_extension.CURRENT

    def test_backup_never_clobbers_an_existing_backup(self, tmp_path: Path):
        extension = write_legacy_install(tmp_path)
        occupied = extension.with_name(f"{extension.name}.bak")
        occupied.write_text("an earlier backup", encoding="utf-8")

        pi_extension.install_or_refresh(dry_run=False, home=tmp_path)

        assert occupied.read_text() == "an earlier backup"
        assert extension.with_name(f"{extension.name}.bak.1").exists()

    def test_backup_is_not_a_loadable_ts_file(self, tmp_path: Path):
        # Pi discovers extensions by *.ts; the backup must not be picked up.
        write_legacy_install(tmp_path)

        pi_extension.install_or_refresh(dry_run=False, home=tmp_path)

        extensions_dir = pi_extension.extension_path(tmp_path).parent
        assert [path.name for path in extensions_dir.glob("*.ts")] == ["observal.ts"]


class TestRemove:
    @pytest.mark.parametrize(
        "manifest_version",
        ["0.0.1", CLI_VERSION, "9999.0.0"],
        ids=["stale", "current", "newer"],
    )
    def test_removes_any_managed_install_regardless_of_version(self, tmp_path: Path, manifest_version: str):
        extension = pi_extension.extension_path(tmp_path)
        extension.parent.mkdir(parents=True)
        extension.write_text("content", encoding="utf-8")
        write_json(pi_extension.manifest_path(tmp_path), {"managed": True, "version": manifest_version})

        assert pi_extension.remove(dry_run=False, home=tmp_path) is True
        assert not extension.exists()
        assert not pi_extension.manifest_path(tmp_path).exists()

    def test_removes_a_pre_manifest_install(self, tmp_path: Path):
        extension = write_legacy_install(tmp_path)

        assert pi_extension.remove(dry_run=False, home=tmp_path) is True
        assert not extension.exists()

    def test_leaves_npm_configuration_alone(self, tmp_path: Path):
        settings = tmp_path / ".pi/agent/settings.json"
        write_json(settings, {"packages": ["npm:observal-pi"]})

        assert pi_extension.remove(dry_run=False, home=tmp_path) is False
        assert read_json(settings)["packages"] == ["npm:observal-pi"]

    def test_leaves_unmanaged_file_alone(self, tmp_path: Path):
        extension = pi_extension.extension_path(tmp_path)
        extension.parent.mkdir(parents=True)
        extension.write_text("not ours", encoding="utf-8")

        assert pi_extension.remove(dry_run=False, home=tmp_path) is False
        assert extension.exists()

    def test_dry_run_reports_without_removing(self, tmp_path: Path):
        extension = pi_extension.extension_path(tmp_path)
        extension.parent.mkdir(parents=True)
        extension.write_text(pi_extension.extension_source(), encoding="utf-8")
        write_json(pi_extension.manifest_path(tmp_path), {"managed": True, "version": CLI_VERSION})

        assert pi_extension.remove(dry_run=True, home=tmp_path) is True
        assert extension.exists()


class TestIsNpmConfigured:
    def test_false_when_settings_file_is_absent(self, tmp_path: Path):
        assert pi_extension.is_npm_configured(tmp_path) is False

    def test_true_for_string_and_dict_entries(self, tmp_path: Path):
        write_json(tmp_path / "settings.json", {"packages": [{"source": "npm:observal-pi@1.0.0"}]})
        assert pi_extension.is_npm_configured(tmp_path) is True

    def test_false_for_unrelated_packages(self, tmp_path: Path):
        write_json(tmp_path / "settings.json", {"packages": ["npm:@observal/pi-insights"]})
        assert pi_extension.is_npm_configured(tmp_path) is False

    def test_false_when_settings_json_is_invalid(self, tmp_path: Path):
        settings = tmp_path / "settings.json"
        settings.write_text("{ not json", encoding="utf-8")
        assert pi_extension.is_npm_configured(tmp_path) is False
