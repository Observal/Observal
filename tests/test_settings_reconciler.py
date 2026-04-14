"""Tests for the declarative settings reconciler.

Covers: fresh install, HTTP→command upgrade, preserve foreign hooks,
add new events, idempotent re-run, env reconciliation, and version tracking.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from observal_cli.hooks_spec import (
    HOOKS_SPEC_VERSION,
    get_desired_env,
    get_desired_hooks,
    is_observal_hook_entry,
    is_observal_matcher_group,
)
from observal_cli.settings_reconciler import (
    reconcile,
    reconcile_env,
    reconcile_hooks,
)

# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture()
def settings_path(tmp_path: Path):
    """Patch CLAUDE_SETTINGS_PATH to a temp file."""
    fake_path = tmp_path / ".claude" / "settings.json"
    with patch("observal_cli.settings_reconciler.CLAUDE_SETTINGS_PATH", fake_path):
        yield fake_path


@pytest.fixture()
def config_path(tmp_path: Path):
    """Patch config module to use a temp dir."""
    fake_config = tmp_path / ".observal" / "config.json"
    fake_config.parent.mkdir(parents=True, exist_ok=True)
    fake_config.write_text("{}", encoding="utf-8")

    def fake_load():
        return json.loads(fake_config.read_text(encoding="utf-8"))

    def fake_save(updates):
        current = fake_load()
        current.update(updates)
        fake_config.write_text(json.dumps(current), encoding="utf-8")

    with (
        patch("observal_cli.settings_reconciler.config.load", side_effect=fake_load),
        patch("observal_cli.settings_reconciler.config.save", side_effect=fake_save),
    ):
        yield fake_config


# ── Hook identification ───────────────────────────────────────


class TestHookIdentification:
    def test_command_hook_identified(self):
        entry = {"type": "command", "command": "/path/to/observal-hook.sh"}
        assert is_observal_hook_entry(entry)

    def test_stop_hook_identified(self):
        entry = {"type": "command", "command": "/path/to/observal-stop-hook.sh"}
        assert is_observal_hook_entry(entry)

    def test_http_hook_identified(self):
        entry = {"type": "http", "url": "http://localhost:8000/api/v1/otel/hooks"}
        assert is_observal_hook_entry(entry)

    def test_foreign_hook_not_identified(self):
        entry = {"type": "command", "command": "/usr/local/bin/my-custom-hook.sh"}
        assert not is_observal_hook_entry(entry)

    def test_metadata_marker_identifies_group(self):
        """Primary identification: _observal metadata key."""
        group = {"_observal": {"version": "3"}, "hooks": [{"type": "command", "command": "/any/path.sh"}]}
        assert is_observal_matcher_group(group)

    def test_legacy_path_identifies_group(self):
        """Fallback: legacy path-based identification for pre-metadata installs."""
        group = {"hooks": [{"type": "command", "command": "/path/observal-hook.sh"}]}
        assert is_observal_matcher_group(group)

    def test_matcher_group_without_observal(self):
        group = {"hooks": [{"type": "command", "command": "/path/other-hook.sh"}]}
        assert not is_observal_matcher_group(group)

    def test_desired_hooks_have_metadata(self):
        """get_desired_hooks injects _observal metadata into every matcher group."""
        desired = get_desired_hooks(
            "/path/observal-hook.sh", "/path/observal-stop-hook.sh", "http://localhost:8000/api/v1/otel/hooks"
        )
        for event, groups in desired.items():
            for group in groups:
                assert "_observal" in group, f"Missing metadata in {event}"
                assert group["_observal"]["version"] == HOOKS_SPEC_VERSION


# ── Hook reconciliation ──────────────────────────────────────


class TestReconcileHooks:
    def test_fresh_install_adds_all_events(self):
        """On empty settings, all desired events are added."""
        desired = get_desired_hooks(
            "/path/observal-hook.sh", "/path/observal-stop-hook.sh", "http://localhost:8000/api/v1/otel/hooks"
        )
        merged, changes = reconcile_hooks({}, desired)

        assert set(merged.keys()) == set(desired.keys())
        assert len(changes) == len(desired)
        assert all(c.startswith("+ ") for c in changes)

    def test_preserves_foreign_hooks(self):
        """Non-Observal hooks on the same event are kept."""
        foreign_group = {"hooks": [{"type": "command", "command": "/usr/bin/my-linter.sh"}]}
        current = {
            "PreToolUse": [foreign_group],
        }
        desired = get_desired_hooks("/path/observal-hook.sh", None, "http://localhost:8000/api/v1/otel/hooks")

        merged, changes = reconcile_hooks(current, desired)

        # Foreign group should still be there, plus the new Observal group
        pre_tool_groups = merged["PreToolUse"]
        assert len(pre_tool_groups) == 2
        assert pre_tool_groups[0] == foreign_group  # Foreign first
        assert is_observal_matcher_group(pre_tool_groups[1])  # Observal second

    def test_upgrades_http_to_command(self):
        """Old HTTP hooks (legacy, no metadata) get replaced with command hooks."""
        old_http_group = {"hooks": [{"type": "http", "url": "http://localhost:8000/api/v1/otel/hooks"}]}
        current = {
            "SessionStart": [old_http_group],
        }
        desired = get_desired_hooks("/path/observal-hook.sh", None, "http://localhost:8000/api/v1/otel/hooks")

        merged, changes = reconcile_hooks(current, desired)

        # Should have replaced the HTTP group with the command group
        groups = merged["SessionStart"]
        assert len(groups) == 1
        assert groups[0]["hooks"][0]["type"] == "command"
        assert "_observal" in groups[0]  # New group has metadata
        assert "updated" in changes[0] or "added" in changes[0]

    def test_upgrades_legacy_path_to_metadata(self):
        """Pre-metadata Observal hooks (path-only) get replaced with metadata-bearing groups."""
        old_path_group = {"hooks": [{"type": "command", "command": "/path/observal-hook.sh"}]}
        current = {
            "SessionStart": [old_path_group],
        }
        desired = get_desired_hooks("/path/observal-hook.sh", None, "http://localhost:8000/api/v1/otel/hooks")

        merged, changes = reconcile_hooks(current, desired)

        groups = merged["SessionStart"]
        assert len(groups) == 1
        assert "_observal" in groups[0]

    def test_idempotent_rerun(self):
        """Running reconcile twice with same desired state produces no changes."""
        desired = get_desired_hooks(
            "/path/observal-hook.sh", "/path/observal-stop-hook.sh", "http://localhost:8000/api/v1/otel/hooks"
        )

        # First run: everything is new
        merged, changes1 = reconcile_hooks({}, desired)
        assert len(changes1) > 0

        # Second run: already up to date
        _, changes2 = reconcile_hooks(merged, desired)
        assert len(changes2) == 0

    def test_foreign_events_preserved(self):
        """Events not in the desired spec are left alone."""
        current = {
            "MyCustomEvent": [{"hooks": [{"type": "command", "command": "/custom.sh"}]}],
        }
        desired = get_desired_hooks("/path/observal-hook.sh", None, "http://localhost:8000/api/v1/otel/hooks")

        merged, _ = reconcile_hooks(current, desired)

        assert "MyCustomEvent" in merged
        assert merged["MyCustomEvent"] == current["MyCustomEvent"]

    def test_adds_new_events(self):
        """When the spec adds a new event type, it appears after reconcile."""
        # Start with a partial set of events
        desired_full = get_desired_hooks("/path/observal-hook.sh", None, "http://localhost:8000/api/v1/otel/hooks")
        partial = {k: v for k, v in desired_full.items() if k in ("SessionStart", "Stop")}

        merged, _ = reconcile_hooks(partial, desired_full)

        # All desired events should now be present
        for event in desired_full:
            assert event in merged

    def test_stop_has_two_hooks(self):
        """Stop event should have both generic and stop-specific handlers."""
        desired = get_desired_hooks(
            "/path/observal-hook.sh", "/path/observal-stop-hook.sh", "http://localhost:8000/api/v1/otel/hooks"
        )
        stop_groups = desired["Stop"]

        # One matcher group with two hook handlers
        assert len(stop_groups) == 1
        hooks = stop_groups[0]["hooks"]
        assert len(hooks) == 2
        assert "observal-hook.sh" in hooks[0]["command"]
        assert "observal-stop-hook.sh" in hooks[1]["command"]


# ── Env reconciliation ───────────────────────────────────────


class TestReconcileEnv:
    def test_fresh_install_adds_all_keys(self):
        desired = get_desired_env("http://localhost:8000", "test-key")
        merged, changes = reconcile_env({}, desired)

        assert "CLAUDE_CODE_ENABLE_TELEMETRY" in merged
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" in merged
        assert len(changes) == len(desired)

    def test_preserves_foreign_env(self):
        """Non-Observal env vars are never touched."""
        current = {
            "MY_CUSTOM_VAR": "keep-me",
            "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        }
        desired = get_desired_env("http://localhost:8000", "test-key")

        merged, _ = reconcile_env(current, desired)

        assert merged["MY_CUSTOM_VAR"] == "keep-me"

    def test_updates_stale_key(self):
        """Changed Observal env values are updated."""
        current = {
            "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer old-key",
        }
        desired = get_desired_env("http://localhost:8000", "new-key")

        merged, changes = reconcile_env(current, desired)

        assert "new-key" in merged["OTEL_EXPORTER_OTLP_HEADERS"]
        assert any("~ env.OTEL_EXPORTER_OTLP_HEADERS" in c for c in changes)

    def test_idempotent_env(self):
        desired = get_desired_env("http://localhost:8000", "test-key")
        merged, _ = reconcile_env({}, desired)
        _, changes2 = reconcile_env(merged, desired)
        assert len(changes2) == 0


# ── Full reconciliation ──────────────────────────────────────


class TestFullReconcile:
    def test_fresh_install_writes_file(self, settings_path, config_path):
        """Full reconcile on empty settings creates the file."""
        desired_hooks = get_desired_hooks(
            "/path/observal-hook.sh", "/path/observal-stop-hook.sh", "http://localhost:8000/api/v1/otel/hooks"
        )
        desired_env = get_desired_env("http://localhost:8000", "test-key")

        changes = reconcile(desired_hooks, desired_env)

        assert len(changes) > 0
        assert settings_path.exists()

        written = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "hooks" in written
        assert "env" in written
        assert "SessionStart" in written["hooks"]

    def test_preserves_non_hook_settings(self, settings_path, config_path):
        """Non-hook/env settings are preserved."""
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(
                {
                    "model": "opus",
                    "enabledPlugins": {"foo": True},
                }
            ),
            encoding="utf-8",
        )

        desired_hooks = get_desired_hooks("/path/observal-hook.sh", None, "http://localhost:8000/api/v1/otel/hooks")
        desired_env = get_desired_env("http://localhost:8000", "test-key")

        reconcile(desired_hooks, desired_env)

        written = json.loads(settings_path.read_text(encoding="utf-8"))
        assert written["model"] == "opus"
        assert written["enabledPlugins"] == {"foo": True}

    def test_dry_run_does_not_write(self, settings_path, config_path):
        """dry_run=True computes changes but doesn't write."""
        desired_hooks = get_desired_hooks("/path/observal-hook.sh", None, "http://localhost:8000/api/v1/otel/hooks")
        desired_env = get_desired_env("http://localhost:8000", "test-key")

        changes = reconcile(desired_hooks, desired_env, dry_run=True)

        assert len(changes) > 0
        assert not settings_path.exists()

    def test_records_spec_version(self, settings_path, config_path):
        """After reconcile, the applied version is recorded in config."""
        desired_hooks = get_desired_hooks("/path/observal-hook.sh", None, "http://localhost:8000/api/v1/otel/hooks")
        desired_env = get_desired_env("http://localhost:8000", "test-key")

        reconcile(desired_hooks, desired_env)

        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        assert cfg["hooks_spec_version"] == HOOKS_SPEC_VERSION

    def test_no_changes_skips_write(self, settings_path, config_path):
        """When already up to date, the file is not rewritten."""
        desired_hooks = get_desired_hooks("/path/observal-hook.sh", None, "http://localhost:8000/api/v1/otel/hooks")
        desired_env = get_desired_env("http://localhost:8000", "test-key")

        # First reconcile
        reconcile(desired_hooks, desired_env)
        mtime = settings_path.stat().st_mtime

        # Second reconcile — no changes
        import time

        time.sleep(0.01)
        changes = reconcile(desired_hooks, desired_env)

        assert len(changes) == 0
        assert settings_path.stat().st_mtime == mtime  # File untouched
