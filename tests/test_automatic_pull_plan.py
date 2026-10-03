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
    cases = [
        {"mcp_config": {"path": str(root / "mcp.json"), "content": {}}},
        {"agent_profile": {"path": str(root / "elsewhere.md"), "content": "new"}},
        {"skill_components": [{"path": str(skill), "name": "review", "git_url": "https://example.test/repo"}]},
        {
            "skill_components": [
                {"path": str(skill), "name": "review", "skill_md_content": "new", "script_content": "echo hi"}
            ]
        },
    ]
    for change in cases:
        with pytest.raises(plan.InstallSkipError):
            plan.plan_pi_files({**valid, **change}, item, previous)

    # The deployed server adds the same delegation MCP to every Pi install.
    # An unchanged, owned mcp.json is allowed as a verified no-op, not merged.
    mcp = root / "mcp.json"
    delegation = {"mcpServers": {"observal-agents": {"command": "/tmp/python", "args": []}}}
    mcp.write_text(json.dumps(delegation, indent=2) + "\n")
    previous[str(mcp)] = hashlib.sha256(mcp.read_bytes()).hexdigest()
    same = {**valid, "mcp_config": {"path": str(mcp), "content": delegation}}
    assert plan.plan_pi_files(same, item, previous)[mcp] == mcp.read_bytes()
    for changed in (
        {"mcpServers": {"observal-agents": {"command": "/tmp/different", "args": []}}},
        {"mcpServers": {"observal-agents": delegation["mcpServers"]["observal-agents"], "other": {}}},
    ):
        with pytest.raises(plan.InstallSkipError):
            plan.plan_pi_files({**valid, "mcp_config": {"path": str(mcp), "content": changed}}, item, previous)
    mcp.write_text(json.dumps({"mcpServers": {"observal-agents": {}, "other": {}}}))
    with pytest.raises(plan.InstallSkipError):
        plan.plan_pi_files(same, item, previous)
    profile.write_text("locally edited")
    # The plan alone is not an ownership check: verified_files in the normal
    # installer runs first and rejects this edit before any target is written.
    with pytest.raises(plan.InstallSkipError):
        plan.plan_pi_files(valid, item, previous)  # Owned mcp.json cannot silently disappear.
