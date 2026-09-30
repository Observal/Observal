# SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""DeepSeek registration and layer integration across shared entry points."""

from pathlib import Path

from observal_cli.harness import ensure_loaded, get_adapter
from observal_cli.layer import _discover_files
from observal_shared.harness_registry import HARNESS_REGISTRY
from services.harness import ensure_loaded as ensure_server_loaded
from services.harness import get_adapter as get_server_adapter
from services.session_parsers import parse_raw_events


def test_deepseek_is_registered_on_both_sides():
    ensure_loaded()
    ensure_server_loaded()
    assert get_adapter("deepseek").harness_name == "deepseek"
    assert get_server_adapter("deepseek").harness_name == "deepseek"
    assert HARNESS_REGISTRY["deepseek"]["mcp_install_mode"] == "user_only"
    assert not HARNESS_REGISTRY["deepseek"]["mcp_config"]["project"]
    events = parse_raw_events(
        [{"harness": "deepseek", "raw_line": '{"type":"session","version":4,"id":"test","createdAt":1000}'}]
    )
    assert events[0]["event_name"] == "hook_sessionstart"


def test_layer_uses_runtime_dsh_home(tmp_path, monkeypatch):
    user = tmp_path / "user"
    dsh_home = tmp_path / "custom-dsh"
    user.mkdir()
    dsh_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: user)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    patch = dsh_home / "cordis.patch.yml"
    patch.write_text("[]\n")
    hooks = dsh_home / "observal" / "hooks.json"
    hooks.parent.mkdir()
    hooks.write_text("{}\n")
    script = dsh_home / "observal/scripts/check.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\ntrue\n")
    old_home = user / ".dsh"
    old_home.mkdir()
    (old_home / "cordis.patch.yml").write_text("[]\n")

    found = dict((label, path) for path, label in _discover_files("deepseek"))
    assert found["user:cordis.patch.yml"] == patch
    assert found["user:observal/hooks.json"] == hooks
    assert found["user:observal/scripts/check.sh"] == script
    assert all(old_home not in path.parents for path in found.values())


def test_layer_discovers_native_project_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "missing-home"))
    project = tmp_path / "project"
    paths = [".dsh/skills/observal-review/SKILL.md", ".dsh/skills/helper.md", ".agents/skills/shared/SKILL.md"]
    for name in paths:
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nname: helper\ndescription: Help with tasks\n---\nInstructions.\n")
    found = {label for _path, label in _discover_files("deepseek", str(project))}
    assert {f"project:{path}" for path in paths} <= found
