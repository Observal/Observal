# SPDX-License-Identifier: Apache-2.0

"""The Pi installer is fail-closed; startup does not invoke it yet."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from observal_cli import auto_update_install as installer
from observal_cli import auto_update_policy as policy
from observal_cli import client, config, install_baseline, installed_updates, lockfile, update_preflight

REGISTRY = "https://example.test"
AGENT = "11111111-1111-4111-8111-111111111111"


@pytest.fixture()
def managed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    home = tmp_path / "home"
    root = home / ".pi" / "agent" / "agents" / "reviewer"
    root.mkdir(parents=True)
    profile = root / "AGENTS.md"
    profile.write_text("old profile")
    directory = tmp_path / "workspace"
    directory.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(policy, "POLICY_PATH", tmp_path / "policy.json")
    monkeypatch.setattr(policy, "GATE_DIR", tmp_path / "gates")
    monkeypatch.setattr(install_baseline, "BASELINE_DIR", tmp_path / "baseline")
    monkeypatch.setattr(lockfile, "LOCKFILE_PATH", tmp_path / "lockfile.json")
    monkeypatch.setattr(lockfile, "_LOCKFILE_LOCK", tmp_path / "lockfile.lock")
    monkeypatch.setattr(lockfile, "_record_capability_use", lambda **_: None)
    credentials = {"server_url": REGISTRY, "access_token": "local-token", "user_id": "alice"}
    monkeypatch.setattr(config, "load", lambda: credentials.copy())
    monkeypatch.setattr(config, "load_persisted", lambda: credentials.copy())
    monkeypatch.setattr(config, "get_or_exit", lambda **_: credentials.copy())
    policy.set_policy(REGISTRY, enabled=True)
    lockfile.upsert_agent(
        "pi",
        name="reviewer",
        agent_id=AGENT,
        version="1.0.0",
        scope="user",
        directory=str(directory),
        components=[],
        namespace="alice",
        slug="reviewer",
        local_name="reviewer",
        lock_status="locked",
        lock_digest="old-digest",
    )
    install_baseline.capture(
        registry=REGISTRY,
        harness="pi",
        agent_id=AGENT,
        scope="user",
        root=str(directory),
        version="1.0.0",
        lock_digest="old-digest",
        written_paths=[str(profile)],
    )
    release = {
        "version": "2.0.0",
        "status": "approved",
        "supported_harnesses": ["pi"],
        "description": "Author notes",
        "components": [],
    }
    snippet = {"agent_profile": {"path": "~/.pi/agent/agents/reviewer/AGENTS.md", "content": "new profile"}}
    response = {
        "agent_id": AGENT,
        "harness": "pi",
        "version": "2.0.0",
        "config_snippet": snippet,
        "lock": {"status": "locked", "digest": "new-digest", "components": [], "problems": []},
    }

    def get(path: str, **_kwargs):
        return (
            release
            if path.endswith("/versions/2.0.0")
            else {
                "id": AGENT,
                "latest_approved_version": "2.0.0",
                "namespace": "alice",
                "slug": "reviewer",
            }
        )

    monkeypatch.setattr(client, "get", get)
    post = MagicMock(return_value=response)
    monkeypatch.setattr(client, "post_public", post)
    item = installed_updates.compare(
        installed_updates.inventory_for_context("pi", str(directory)), verify_releases=True
    )[0]
    return {
        "directory": directory,
        "profile": profile,
        "item": item,
        "release": release,
        "snippet": snippet,
        "response": response,
        "post": post,
    }


def apply(managed: dict) -> dict:
    return installer.apply_pi_agent(
        managed["item"],
        registry=REGISTRY,
        account="alice",
        deadline=time.monotonic() + 90,
        reserve_recovery=lambda _backups: None,
    )


def assert_old(managed: dict) -> None:
    assert managed["profile"].read_text() == "old profile"
    assert (
        lockfile.installed_agent("pi", AGENT, scope="user", directory=str(managed["directory"]))["version"] == "1.0.0"
    )
    assert install_baseline.verified_files(
        registry=REGISTRY,
        harness="pi",
        agent_id=AGENT,
        scope="user",
        root=str(managed["directory"]),
        version="1.0.0",
        lock_digest="old-digest",
    )


def test_verifies_installed_files_lock_and_next_session_state(managed: dict) -> None:
    result = apply(managed)
    assert result == {
        "status": "updated",
        "id": AGENT,
        "current_version": "1.0.0",
        "target_version": "2.0.0",
        "description": "Author notes",
        "effective_in_current_session": "no",
        "reload_required": True,
    }
    assert managed["profile"].read_text() == "new profile"
    entry = lockfile.installed_agent("pi", AGENT, scope="user", directory=str(managed["directory"]))
    assert entry["version"] == "2.0.0" and entry["lock_digest"] == "new-digest"
    assert install_baseline.verified_files(
        registry=REGISTRY,
        harness="pi",
        agent_id=AGENT,
        scope="user",
        root=str(managed["directory"]),
        version="2.0.0",
        lock_digest="new-digest",
    )
    assert list(managed["profile"].parent.glob(".observal-update-*")) == []
    managed["post"].assert_called_once()
    assert managed["post"].call_args.args[1]["strict"] is True


def test_missing_or_failed_recovery_journal_never_mutates(managed: dict) -> None:
    with pytest.raises(installer.InstallSkipError, match="prepared install"):
        installer.apply_pi_agent(managed["item"], registry=REGISTRY, account="alice", deadline=time.monotonic() + 90)
    assert_old(managed)
    assert not list(managed["profile"].parent.glob(".observal-update-*"))

    def cannot_record(backups: dict[Path, Path]) -> None:
        assert next(iter(backups.values())).read_text() == "old profile"
        raise OSError("journal disk full")

    with pytest.raises(installer.InstallSkipError, match="prepared install"):
        installer.apply_pi_agent(
            managed["item"],
            registry=REGISTRY,
            account="alice",
            deadline=time.monotonic() + 90,
            reserve_recovery=cannot_record,
        )
    assert_old(managed)
    assert not list(managed["profile"].parent.glob(".observal-update-*"))


def test_shutdown_before_admission_does_not_fetch_or_write(managed: dict) -> None:
    with pytest.raises(installer.InstallSkipError, match="session ended"):
        installer.apply_pi_agent(
            managed["item"],
            registry=REGISTRY,
            account="alice",
            deadline=time.monotonic() + 90,
            shutdown_requested=lambda: True,
        )
    managed["post"].assert_not_called()
    assert_old(managed)


def test_shutdown_after_staging_skips_without_mutation(managed: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    stopped = False
    stage = installer._stage

    def stage_then_shutdown(*args):
        nonlocal stopped
        result = stage(*args)
        stopped = True
        return result

    monkeypatch.setattr(installer, "_stage", stage_then_shutdown)
    with pytest.raises(installer.InstallSkipError):
        installer.apply_pi_agent(
            managed["item"],
            registry=REGISTRY,
            account="alice",
            deadline=time.monotonic() + 90,
            shutdown_requested=lambda: stopped,
            reserve_recovery=lambda _backups: None,
        )
    assert_old(managed)
    assert list(managed["profile"].parent.glob(".observal-update-*")) == []


def test_shutdown_racing_after_last_check_can_still_commit(managed: dict) -> None:
    checks = 0
    stopped = False

    def shutdown_requested() -> bool:
        nonlocal checks, stopped
        checks += 1
        if checks == 3:
            # Marker appears immediately *after* the last observation but
            # before the first replacement. This is not atomic with Pi.
            stopped = True
            return False
        return stopped

    result = installer.apply_pi_agent(
        managed["item"],
        registry=REGISTRY,
        account="alice",
        deadline=time.monotonic() + 90,
        shutdown_requested=shutdown_requested,
        reserve_recovery=lambda _backups: None,
    )
    assert stopped and checks == 3 and result["status"] == "updated"
    assert managed["profile"].read_text() == "new profile"


def test_shutdown_during_commit_finishes_verified_install(managed: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    stopped = False
    replace = installer.os.replace

    def replace_then_shutdown(source: Path, target: Path) -> None:
        nonlocal stopped
        replace(source, target)
        if Path(target) == managed["profile"]:
            stopped = True

    monkeypatch.setattr(installer.os, "replace", replace_then_shutdown)
    result = installer.apply_pi_agent(
        managed["item"],
        registry=REGISTRY,
        account="alice",
        deadline=time.monotonic() + 90,
        shutdown_requested=lambda: stopped,
        reserve_recovery=lambda _backups: None,
    )
    assert stopped and result["status"] == "updated"
    assert managed["profile"].read_text() == "new profile"
    assert (
        lockfile.installed_agent("pi", AGENT, scope="user", directory=str(managed["directory"]))["version"] == "2.0.0"
    )


def _add_managed_skill(managed: dict) -> Path:
    skill_dir = managed["profile"].parent / "skills" / "review"
    skill_dir.mkdir(parents=True)
    skill = skill_dir / "SKILL.md"
    skill.write_text("old skill")
    lockfile.upsert_agent(
        "pi",
        name="reviewer",
        agent_id=AGENT,
        version="1.0.0",
        scope="user",
        directory=str(managed["directory"]),
        components=[{"type": "skill", "id": "skill-id", "version": "1.0.0"}],
        namespace="alice",
        slug="reviewer",
        local_name="reviewer",
        lock_status="locked",
        lock_digest="old-digest",
    )
    install_baseline.capture(
        registry=REGISTRY,
        harness="pi",
        agent_id=AGENT,
        scope="user",
        root=str(managed["directory"]),
        version="1.0.0",
        lock_digest="old-digest",
        written_paths=[str(managed["profile"]), str(skill_dir)],
    )
    managed["release"]["components"] = [
        {"component_type": "skill", "component_id": "skill-id", "resolved_version": "2.0.0"}
    ]
    managed["response"]["lock"]["components"] = [{"type": "skill", "id": "skill-id", "version": "2.0.0"}]
    managed["snippet"]["skill_components"] = [
        {
            "name": "review",
            "path": "~/.pi/agent/agents/reviewer/skills/review/SKILL.md",
            "skill_md_content": "new skill",
        }
    ]
    managed["item"] = installed_updates.compare(
        installed_updates.inventory_for_context("pi", str(managed["directory"])), verify_releases=True
    )[0]
    return skill


def test_registry_direct_skill_updates_only_existing_owned_files(managed: dict) -> None:
    skill = _add_managed_skill(managed)
    apply(managed)
    assert skill.read_text() == "new skill"
    assert managed["profile"].read_text() == "new profile"
    assert install_baseline.verified_files(
        registry=REGISTRY,
        harness="pi",
        agent_id=AGENT,
        scope="user",
        root=str(managed["directory"]),
        version="2.0.0",
        lock_digest="new-digest",
    )


def test_frozen_dirty_legacy_and_changed_version_are_notice_only(managed: dict) -> None:
    policy.set_policy(REGISTRY, enabled=False)
    with pytest.raises(update_preflight.PreflightSkipError, match="frozen"):
        apply(managed)
    policy.set_policy(REGISTRY, enabled=True)
    managed["profile"].write_text("local edit")
    with pytest.raises(update_preflight.PreflightSkipError, match="changed"):
        apply(managed)
    managed["profile"].write_text("old profile")
    entry = lockfile.installed_agent("pi", AGENT, scope="user", directory=str(managed["directory"]))
    lockfile.upsert_agent(
        "pi",
        name="reviewer",
        agent_id=AGENT,
        version="1.1.0",
        scope="user",
        directory=str(managed["directory"]),
        components=[],
        namespace="alice",
        slug="reviewer",
        local_name="reviewer",
        lock_status="locked",
        lock_digest=entry["lock_digest"],
    )
    with pytest.raises(installer.InstallSkipError, match="installed version"):
        apply(managed)
    managed["post"].assert_not_called()


@pytest.mark.parametrize(
    "bad",
    [
        {"mcp_config": {"path": "~/.pi/agent/agents/reviewer/mcp.json", "content": {}}},
        {"mcp_setup_commands": [["sh", "-c", "echo unsafe"]]},
        {"skill_components": [{"name": "skill", "git_url": "https://example.test/git"}]},
    ],
)
def test_unsupported_plan_never_writes(managed: dict, bad: dict) -> None:
    managed["response"]["config_snippet"].update(bad)
    with pytest.raises(installer.InstallSkipError):
        apply(managed)
    assert_old(managed)


def test_generated_response_must_be_for_the_same_agent_and_harness(managed: dict) -> None:
    managed["response"]["agent_id"] = "different-agent"
    with pytest.raises(installer.InstallSkipError, match="approved target"):
        apply(managed)
    assert_old(managed)
    managed["response"]["agent_id"] = AGENT
    managed["response"]["harness"] = "cursor"
    with pytest.raises(installer.InstallSkipError, match="approved target"):
        apply(managed)
    assert_old(managed)


def test_target_path_and_lock_pin_must_match_exactly(managed: dict) -> None:
    managed["snippet"]["agent_profile"]["path"] = "~/.pi/agent/agents/other/AGENTS.md"
    with pytest.raises(installer.InstallSkipError, match=r"location|creates a file"):
        apply(managed)
    managed["snippet"]["agent_profile"]["path"] = "~/.pi/agent/agents/reviewer/AGENTS.md"
    managed["release"]["components"] = [{"component_type": "skill", "component_id": "new", "resolved_version": "1.0"}]
    with pytest.raises(update_preflight.PreflightSkipError, match="adds or removes"):
        apply(managed)
    assert_old(managed)


def test_write_failure_restores_old_file_and_metadata(managed: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    original = installer.os.replace
    hit = False

    def fail_after_file(src, dst):
        nonlocal hit
        if str(src).endswith(".next") and not hit:
            hit = True
            original(src, dst)
            # Simulate an interrupted metadata write after the first replacement.
            raise OSError("interrupted")
        return original(src, dst)

    monkeypatch.setattr(installer.os, "replace", fail_after_file)
    with pytest.raises(installer.InstallFailedError) as failure:
        apply(managed)
    assert failure.value.partial is False
    assert_old(managed)
    assert list(managed["profile"].parent.glob(".observal-update-*")) == []


def test_failed_rollback_is_reported_partial_not_success(managed: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    original = installer.os.replace

    def fail_rollback(src, dst):
        if str(src).endswith(".restore"):
            raise OSError("restore denied")
        if str(src).endswith(".next"):
            original(src, dst)
            raise OSError("write interrupted")
        return original(src, dst)

    monkeypatch.setattr(installer.os, "replace", fail_rollback)
    with pytest.raises(installer.InstallFailedError) as failure:
        apply(managed)
    assert failure.value.partial is True
    recovery = failure.value.result
    assert recovery["partial"] is True
    assert recovery["recovery_dir"] == failure.value.recovery_dir
    assert Path(recovery["recovery_dir"]).is_dir()
    assert Path(recovery["recovery_dir"]).stat().st_mode & 0o777 == 0o700
    assert len(recovery["recovery_files"]) == 1
    assert recovery["recovery_files"][0]["target"] == str(managed["profile"])
    assert Path(recovery["recovery_files"][0]["backup"]).read_text() == "old profile"
    assert "old profile" not in str(recovery)  # references, never file contents
    assert managed["profile"].read_text() == "new profile"
    with pytest.raises(install_baseline.BaselineError):
        install_baseline.verified_files(
            registry=REGISTRY,
            harness="pi",
            agent_id=AGENT,
            scope="user",
            root=str(managed["directory"]),
            version="1.0.0",
            lock_digest="old-digest",
        )


def test_edit_between_replacements_is_not_overwritten(managed: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    skill = _add_managed_skill(managed)
    original = installer.os.replace

    def edit_later_file(src, dst):
        result = original(src, dst)
        if str(src).endswith("0.next"):
            skill.write_text("editor changed skill")
        return result

    monkeypatch.setattr(installer.os, "replace", edit_later_file)
    with pytest.raises(installer.InstallFailedError) as failure:
        apply(managed)
    assert failure.value.partial is True  # the editor's file is now dirty
    assert managed["profile"].read_text() == "old profile"  # our own replacement was undone
    assert skill.read_text() == "editor changed skill"
    backups = {row["target"]: Path(row["backup"]) for row in failure.value.result["recovery_files"]}
    assert backups[str(managed["profile"])].read_text() == "old profile"
    assert backups[str(skill)].read_text() == "old skill"
    assert (
        lockfile.installed_agent("pi", AGENT, scope="user", directory=str(managed["directory"]))["version"] == "1.0.0"
    )


def test_rollback_does_not_overwrite_a_new_edit_to_committed_file(
    managed: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = _add_managed_skill(managed)
    original = installer.os.replace

    def edit_committed_file(src, dst):
        if str(src).endswith("1.next"):
            raise OSError("second write interrupted")
        result = original(src, dst)
        if str(src).endswith("0.next"):
            managed["profile"].write_text("editor changed profile")
        return result

    monkeypatch.setattr(installer.os, "replace", edit_committed_file)
    with pytest.raises(installer.InstallFailedError) as failure:
        apply(managed)
    assert failure.value.partial is True
    assert managed["profile"].read_text() == "editor changed profile"
    assert skill.read_text() == "old skill"
    backups = {row["target"]: Path(row["backup"]) for row in failure.value.result["recovery_files"]}
    assert backups[str(managed["profile"])].read_text() == "old profile"
    assert backups[str(skill)].read_text() == "old skill"


def test_tracking_failure_rolls_back_without_false_success(managed: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    original = lockfile.upsert_agent
    first = True

    def fail_after_tracking(*args, **kwargs):
        nonlocal first
        original(*args, **kwargs)
        if first:
            first = False
            raise OSError("write acknowledged then failed")

    monkeypatch.setattr(lockfile, "upsert_agent", fail_after_tracking)
    with pytest.raises(installer.InstallFailedError) as failure:
        apply(managed)
    assert failure.value.partial is False
    assert_old(managed)


def test_manual_pi_lock_prevents_simultaneous_auto_write(managed: dict) -> None:
    entered = threading.Event()
    release = threading.Event()

    def manual_pull() -> None:
        with policy.pi_install_lock(REGISTRY):
            entered.set()
            assert release.wait(5)

    thread = threading.Thread(target=manual_pull)
    thread.start()
    assert entered.wait(3)
    try:
        with pytest.raises(policy.GateBusyError):
            installer.apply_pi_agent(
                managed["item"], registry=REGISTRY, account="alice", deadline=time.monotonic() + 0.1
            )
        assert_old(managed)
        managed["post"].assert_not_called()
    finally:
        release.set()
        thread.join(5)


def test_freeze_waits_until_verified_install_completes(managed: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return managed["response"]

    managed["post"].side_effect = blocked
    results: list[object] = []
    install_thread = threading.Thread(target=lambda: results.append(apply(managed)))
    install_thread.start()
    assert entered.wait(3)
    freeze_thread = threading.Thread(target=lambda: results.append(policy.set_policy(REGISTRY, enabled=False)))
    freeze_thread.start()
    try:
        time.sleep(0.1)
        assert freeze_thread.is_alive()
    finally:
        release.set()
        install_thread.join(5)
        freeze_thread.join(5)
    assert len(results) == 2
    assert results[0]["status"] == "updated"
    assert results[1]["effective"] is False
