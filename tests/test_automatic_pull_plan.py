# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Only pre-owned Pi profile paths are eligible for the normal installer at startup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from observal_cli import automatic_pull_plan as plan


def test_startup_plan_reuses_only_existing_profile_and_plain_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    root = home / ".pi/agent/agents/reviewer"
    profile = root / "AGENTS.md"
    skill = root / "skills/review/SKILL.md"
    skill.parent.mkdir(parents=True)
    profile.write_text("old profile")
    skill.write_text("old skill")
    item = {"directory": str(tmp_path), "local_name": "reviewer"}
    previous = {
        str(profile): hashlib.sha256(profile.read_bytes()).hexdigest(),
        str(skill): hashlib.sha256(skill.read_bytes()).hexdigest(),
    }
    valid = {
        "agent_profile": {"path": str(profile), "content": "new profile"},
        "skill_components": [{"path": str(skill), "name": "review", "skill_md_content": "new skill"}],
    }
    assert plan.plan_pi_files(valid, item, previous) == {
        profile: b"new profile",
        skill: b"new skill",
    }
    script = skill.parent / "scripts/run.sh"
    script.parent.mkdir()
    script.write_text("echo old\n")
    previous[str(script)] = hashlib.sha256(script.read_bytes()).hexdigest()
    with_script = {
        **valid,
        "skill_components": [
            {**valid["skill_components"][0], "script_content": "echo new\n", "script_filename": "run.sh"}
        ],
    }
    assert plan.plan_pi_files(with_script, item, previous)[script] == b"echo new\n"
    previous.pop(str(script))
    script.unlink()
    # A target that adds a script has no prior ownership proof or backup plan.
    with pytest.raises(plan.InstallSkipError):
        plan.plan_pi_files(with_script, item, previous)
    cases = [
        {"mcp_config": {"path": str(root / "mcp.json"), "content": {}}},
        {"agent_profile": {"path": str(root / "elsewhere.md"), "content": "new"}},
        {"skill_components": [{"path": str(skill), "name": "review", "git_url": "https://example.test/repo"}]},
        {
            "skill_components": [
                {
                    "path": str(skill),
                    "name": "review",
                    "skill_md_content": "new",
                    "script_content": "echo hi",
                    "script_filename": "../unsafe.sh",
                }
            ]
        },
    ]
    for change in cases:
        with pytest.raises(plan.InstallSkipError):
            plan.plan_pi_files({**valid, **change}, item, previous)

    # The deployed server adds a delegation MCP to every Pi install.
    # An unchanged owned mcp.json is a verified no-op; changed existing
    # entries get the normal writer's exact merged bytes.
    mcp = root / "mcp.json"
    delegation = {"mcpServers": {"observal-agents": {"command": "/tmp/python", "args": []}}}
    mcp.write_text(json.dumps(delegation, indent=2) + "\n")
    previous[str(mcp)] = hashlib.sha256(mcp.read_bytes()).hexdigest()
    same = {**valid, "mcp_config": {"path": str(mcp), "content": delegation}}
    assert plan.plan_pi_files(same, item, previous)[mcp] == mcp.read_bytes()
    changed = {"mcpServers": {"observal-agents": {"command": "/tmp/different", "args": []}}}
    assert (
        plan.plan_pi_files({**valid, "mcp_config": {"path": str(mcp), "content": changed}}, item, previous)[mcp]
        == (json.dumps(changed, indent=2) + "\n").encode()
    )
    added = {"mcpServers": {"observal-agents": delegation["mcpServers"]["observal-agents"], "other": {}}}
    with pytest.raises(plan.InstallSkipError):
        plan.plan_pi_files({**valid, "mcp_config": {"path": str(mcp), "content": added}}, item, previous)
    # An approved version may change an existing bundled MCP reference without
    # adding a key to this fully owned per-agent config.
    owned = {"mcpServers": {**delegation["mcpServers"], "search": {"command": "/tmp/search-v1"}}}
    mcp.write_text(json.dumps(owned, indent=2) + "\n")
    previous[str(mcp)] = hashlib.sha256(mcp.read_bytes()).hexdigest()
    updated = {"mcpServers": {**delegation["mcpServers"], "search": {"command": "/tmp/search-v2"}}}
    assert (
        plan.plan_pi_files({**valid, "mcp_config": {"path": str(mcp), "content": updated}}, item, previous)[mcp]
        == (json.dumps(updated, indent=2) + "\n").encode()
    )
    mcp.write_text(json.dumps({"mcpServers": {"observal-agents": {}, "other": {}}}))
    with pytest.raises(plan.InstallSkipError):
        plan.plan_pi_files(same, item, previous)
    profile.write_text("locally edited")
    # The plan alone is not an ownership check: verified_files in the normal
    # installer runs first and rejects this edit before any target is written.
    with pytest.raises(plan.InstallSkipError):
        plan.plan_pi_files(valid, item, previous)  # Owned mcp.json cannot silently disappear.
