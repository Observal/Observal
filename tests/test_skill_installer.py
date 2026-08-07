# SPDX-FileCopyrightText: 2026 EuanTop <euan@mail.bnu.edu.cn>
# SPDX-License-Identifier: Apache-2.0

"""Tests for adapter-driven bundled Observal skill installation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from observal_cli.skill_installer import BUNDLED_SKILL_NAMES, install_observal_skill

SKILLS_BASE = Path(__file__).parents[1] / "observal_cli" / "skills"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def bundled_content(skill_name: str) -> bytes:
    return (SKILLS_BASE / skill_name / "SKILL.md").read_bytes()


def mark_pi_installed(home: Path) -> None:
    (home / ".pi" / "agent").mkdir(parents=True)


def mark_codex_installed(home: Path) -> None:
    (home / ".codex").mkdir()


def test_pi_only_installs_native_skill_copies(tmp_path: Path):
    mark_pi_installed(tmp_path)

    result = install_observal_skill()

    assert result.installed_harnesses == ("pi",)
    for skill_name in BUNDLED_SKILL_NAMES:
        native = tmp_path / ".pi" / "agent" / "skills" / skill_name / "SKILL.md"
        assert native.read_bytes() == bundled_content(skill_name)
        assert not (tmp_path / ".agents" / "skills" / skill_name / "SKILL.md").exists()


def test_codex_only_installs_shared_agent_skill_copies(tmp_path: Path):
    mark_codex_installed(tmp_path)

    result = install_observal_skill()

    assert result.installed_harnesses == ("codex",)
    assert len(result.changed_paths) == len(BUNDLED_SKILL_NAMES)
    for skill_name in BUNDLED_SKILL_NAMES:
        shared = tmp_path / ".agents" / "skills" / skill_name / "SKILL.md"
        assert shared.read_bytes() == bundled_content(skill_name)
        assert not (tmp_path / ".pi" / "agent" / "skills" / skill_name / "SKILL.md").exists()
    assert not (tmp_path / ".gemini" / "antigravity-cli").exists()


def test_codex_and_pi_share_one_copy_per_skill(tmp_path: Path):
    mark_codex_installed(tmp_path)
    mark_pi_installed(tmp_path)

    result = install_observal_skill()

    assert result.installed_harnesses == ("codex", "pi")
    assert len(result.changed_paths) == len(BUNDLED_SKILL_NAMES)
    for skill_name in BUNDLED_SKILL_NAMES:
        shared = tmp_path / ".agents" / "skills" / skill_name / "SKILL.md"
        assert shared.read_bytes() == bundled_content(skill_name)
        assert not (tmp_path / ".pi" / "agent" / "skills" / skill_name / "SKILL.md").exists()


def test_pi_reuses_an_identical_existing_shared_copy_without_codex(tmp_path: Path):
    mark_pi_installed(tmp_path)
    shared = tmp_path / ".agents" / "skills" / "observal" / "SKILL.md"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(bundled_content("observal"))

    result = install_observal_skill()

    assert "pi" in result.installed_harnesses
    assert shared.read_bytes() == bundled_content("observal")
    assert not (tmp_path / ".pi" / "agent" / "skills" / "observal" / "SKILL.md").exists()


def test_identical_stale_pi_copy_is_removed(tmp_path: Path):
    mark_codex_installed(tmp_path)
    mark_pi_installed(tmp_path)
    native = tmp_path / ".pi" / "agent" / "skills" / "observal" / "SKILL.md"
    native.parent.mkdir(parents=True)
    native.write_bytes(bundled_content("observal"))

    result = install_observal_skill()

    assert not native.exists()
    assert native in result.changed_paths
    assert result.warnings == ()


def test_divergent_pi_copy_is_preserved_and_reported(tmp_path: Path):
    mark_codex_installed(tmp_path)
    mark_pi_installed(tmp_path)
    native = tmp_path / ".pi" / "agent" / "skills" / "observal" / "SKILL.md"
    native.parent.mkdir(parents=True)
    native.write_text("user customization", encoding="utf-8")

    result = install_observal_skill()

    assert native.read_text(encoding="utf-8") == "user customization"
    assert any("Preserved divergent" in warning and str(native) in warning for warning in result.warnings)


def test_unrelated_pi_skill_is_left_untouched(tmp_path: Path):
    mark_codex_installed(tmp_path)
    mark_pi_installed(tmp_path)
    unrelated = tmp_path / ".pi" / "agent" / "skills" / "custom" / "SKILL.md"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("custom skill", encoding="utf-8")

    install_observal_skill()

    assert unrelated.read_text(encoding="utf-8") == "custom skill"


def test_repeated_combined_install_keeps_the_same_layout(tmp_path: Path):
    mark_codex_installed(tmp_path)
    mark_pi_installed(tmp_path)

    first = install_observal_skill()
    second = install_observal_skill()

    assert first.installed_harnesses == second.installed_harnesses == ("codex", "pi")
    assert second.changed_paths == ()
    assert second.warnings == ()
    for skill_name in BUNDLED_SKILL_NAMES:
        assert (tmp_path / ".agents" / "skills" / skill_name / "SKILL.md").is_file()
        assert not (tmp_path / ".pi" / "agent" / "skills" / skill_name / "SKILL.md").exists()


def test_failed_shared_write_does_not_delete_working_native_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    mark_codex_installed(tmp_path)
    mark_pi_installed(tmp_path)
    native = tmp_path / ".pi" / "agent" / "skills" / "observal" / "SKILL.md"
    native.parent.mkdir(parents=True)
    native.write_bytes(bundled_content("observal"))
    shared = tmp_path / ".agents" / "skills" / "observal" / "SKILL.md"
    original_write_bytes = Path.write_bytes

    def fail_shared_write(path: Path, data: bytes) -> int:
        if path == shared:
            raise OSError("permission denied")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_shared_write)

    result = install_observal_skill()

    assert native.is_file()
    assert any("permission denied" in warning for warning in result.warnings)
    assert any("replacement at" in warning for warning in result.warnings)


def test_kiro_adapter_wires_active_profile_resources(tmp_path: Path):
    settings = tmp_path / ".kiro" / "settings" / "cli.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"chat.defaultAgent": "default"}), encoding="utf-8")
    profile = tmp_path / ".kiro" / "agents" / "default.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps({"resources": ["file://AGENTS.md"]}), encoding="utf-8")

    first = install_observal_skill()
    second = install_observal_skill()

    resources = json.loads(profile.read_text(encoding="utf-8"))["resources"]
    assert first.installed_harnesses == second.installed_harnesses == ("kiro",)
    assert second.changed_paths == ()
    assert second.warnings == ()
    assert resources == ["file://AGENTS.md", "skill://~/.kiro/skills/*/SKILL.md"]
