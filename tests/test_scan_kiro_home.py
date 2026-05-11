# SPDX-FileCopyrightText: 2026 Devaansh Dubey <devaanshdubey@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for _scan_kiro_home: agent, MCP, skill, and hook discovery."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from observal_cli.cmd_scan import _scan_kiro_home

if TYPE_CHECKING:
    from pathlib import Path


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestEmptyKiroDir:
    def test_nonexistent_dir_returns_empty(self, tmp_path: Path):
        mcps, skills, hooks, agents = _scan_kiro_home(tmp_path / "nonexistent")
        assert mcps == []
        assert skills == []
        assert hooks == []
        assert agents == []

    def test_empty_kiro_dir_returns_empty(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        kiro.mkdir()
        mcps, skills, hooks, agents = _scan_kiro_home(kiro)
        assert mcps == []
        assert skills == []
        assert hooks == []
        assert agents == []


class TestKiroMcpDiscovery:
    def test_discovers_mcp_servers(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        _write_json(
            kiro / "settings" / "mcp.json",
            {
                "mcpServers": {
                    "my-server": {"command": "npx", "args": ["-y", "my-server"]},
                    "http-server": {"url": "http://localhost:3000"},
                }
            },
        )
        mcps, _, _, _ = _scan_kiro_home(kiro)
        names = [m.name for m in mcps]
        assert "my-server" in names
        assert "http-server" in names

    def test_mcp_fields_populated(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        _write_json(
            kiro / "settings" / "mcp.json",
            {"mcpServers": {"srv": {"command": "python", "args": ["-m", "srv"], "env": {"KEY": "val"}}}},
        )
        mcps, _, _, _ = _scan_kiro_home(kiro)
        assert len(mcps) == 1
        m = mcps[0]
        assert m.name == "srv"
        assert m.command == "python"
        assert m.args == ["-m", "srv"]
        assert m.source == "kiro:global"

    def test_bare_format_mcp_json(self, tmp_path: Path):
        """Bare format: top-level keys are server names (no mcpServers wrapper)."""
        kiro = tmp_path / ".kiro"
        _write_json(
            kiro / "settings" / "mcp.json",
            {"bare-srv": {"command": "node", "args": ["index.js"]}},
        )
        mcps, _, _, _ = _scan_kiro_home(kiro)
        assert any(m.name == "bare-srv" for m in mcps)

    def test_malformed_mcp_json_skipped(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        (kiro / "settings").mkdir(parents=True)
        (kiro / "settings" / "mcp.json").write_text("not valid json{{{")
        mcps, _, _, _ = _scan_kiro_home(kiro)
        assert mcps == []

    def test_missing_mcp_json_returns_empty(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        kiro.mkdir()
        mcps, _, _, _ = _scan_kiro_home(kiro)
        assert mcps == []


class TestKiroAgentDiscovery:
    def test_discovers_agent(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        _write_json(
            kiro / "agents" / "coder.json",
            {
                "name": "coder",
                "description": "A coding agent",
                "model": "claude-sonnet-4",
                "prompt": "You are a coder.",
            },
        )
        _, _, _, agents = _scan_kiro_home(kiro)
        assert len(agents) == 1
        a = agents[0]
        assert a.name == "coder"
        assert a.description == "A coding agent"
        assert a.model_name == "claude-sonnet-4"
        assert a.prompt == "You are a coder."
        assert "coder.json" in a.source_file

    def test_agent_name_falls_back_to_stem(self, tmp_path: Path):
        """If JSON has no 'name' key, use the filename stem."""
        kiro = tmp_path / ".kiro"
        _write_json(kiro / "agents" / "reviewer.json", {"prompt": "Review code."})
        _, _, _, agents = _scan_kiro_home(kiro)
        assert agents[0].name == "reviewer"

    def test_multiple_agents_discovered(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        for name in [
            "coder",
            "frontend",
            "backend",
            "fullstack",
            "devops",
            "debugger",
            "reviewer",
            "researcher",
            "tester",
            "docs",
            "database",
            "api-designer",
        ]:
            _write_json(
                kiro / "agents" / f"{name}.json",
                {"name": name, "description": f"{name} agent"},
            )
        _, _, _, agents = _scan_kiro_home(kiro)
        assert len(agents) == 12
        names = {a.name for a in agents}
        assert "coder" in names
        assert "api-designer" in names

    def test_malformed_agent_json_skipped(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        (kiro / "agents").mkdir(parents=True)
        (kiro / "agents" / "bad.json").write_text("{broken")
        _, _, _, agents = _scan_kiro_home(kiro)
        assert agents == []

    def test_agent_mcpservers_extracted(self, tmp_path: Path):
        """MCPs embedded in an agent file are also discovered."""
        kiro = tmp_path / ".kiro"
        _write_json(
            kiro / "agents" / "coder.json",
            {
                "name": "coder",
                "mcpServers": {
                    "agent-mcp": {"command": "uvx", "args": ["agent-mcp"]},
                },
            },
        )
        mcps, _, _, _ = _scan_kiro_home(kiro)
        assert any(m.name == "agent-mcp" for m in mcps)
        agent_mcp = next(m for m in mcps if m.name == "agent-mcp")
        assert agent_mcp.source == "kiro:agent:coder"

    def test_agent_hooks_extracted(self, tmp_path: Path):
        """Hooks embedded in an agent file are discovered."""
        kiro = tmp_path / ".kiro"
        _write_json(
            kiro / "agents" / "coder.json",
            {
                "name": "coder",
                "hooks": {
                    "preToolUse": [{"command": "echo pre"}],
                    "postToolUse": [{"command": "echo post"}],
                },
            },
        )
        _, _, hooks, _ = _scan_kiro_home(kiro)
        events = {h.event for h in hooks}
        assert "preToolUse" in events
        assert "postToolUse" in events
        assert all(h.source == "kiro:agent:coder" for h in hooks)


class TestKiroSkillDiscovery:
    def test_discovers_skill_with_frontmatter(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        _write_text(
            kiro / "skills" / "react-helper" / "SKILL.md",
            "---\ndescription: Helps with React components\ntask_type: frontend\n---\n\nBody text.",
        )
        _, skills, _, _ = _scan_kiro_home(kiro)
        assert len(skills) == 1
        s = skills[0]
        assert s.name == "react-helper"
        assert s.description == "Helps with React components"
        assert s.task_type == "frontend"
        assert s.source == "kiro:skills"

    def test_skill_name_is_parent_directory(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        _write_text(kiro / "skills" / "my-skill" / "SKILL.md", "# My Skill\n\nDoes things.")
        _, skills, _, _ = _scan_kiro_home(kiro)
        assert skills[0].name == "my-skill"

    def test_skill_description_falls_back_to_first_content_line(self, tmp_path: Path):
        """No frontmatter — description should be the first non-empty content line."""
        kiro = tmp_path / ".kiro"
        _write_text(kiro / "skills" / "plain-skill" / "SKILL.md", "Does something useful.\n\nMore details.")
        _, skills, _, _ = _scan_kiro_home(kiro)
        assert skills[0].description == "Does something useful."

    def test_skill_description_falls_back_to_default_when_no_content(self, tmp_path: Path):
        """Empty SKILL.md — description falls back to 'Kiro skill: <name>'."""
        kiro = tmp_path / ".kiro"
        _write_text(kiro / "skills" / "empty-skill" / "SKILL.md", "")
        _, skills, _, _ = _scan_kiro_home(kiro)
        assert skills[0].description == "Kiro skill: empty-skill"

    def test_skill_task_type_defaults_to_general(self, tmp_path: Path):
        """No task_type in frontmatter — should default to 'general'."""
        kiro = tmp_path / ".kiro"
        _write_text(
            kiro / "skills" / "no-type" / "SKILL.md",
            "---\ndescription: A skill\n---\n\nBody.",
        )
        _, skills, _, _ = _scan_kiro_home(kiro)
        assert skills[0].task_type == "general"

    def test_multiple_skills_discovered(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        for skill_name in ["react-helper", "sql-writer", "test-gen"]:
            _write_text(
                kiro / "skills" / skill_name / "SKILL.md",
                f"---\ndescription: {skill_name} skill\n---\n",
            )
        _, skills, _, _ = _scan_kiro_home(kiro)
        assert len(skills) == 3
        names = {s.name for s in skills}
        assert names == {"react-helper", "sql-writer", "test-gen"}

    def test_no_skills_dir_returns_empty(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        kiro.mkdir()
        _, skills, _, _ = _scan_kiro_home(kiro)
        assert skills == []

    def test_nested_skill_md_discovered(self, tmp_path: Path):
        """rglob should find SKILL.md even in deeper nesting."""
        kiro = tmp_path / ".kiro"
        _write_text(
            kiro / "skills" / "deep-skill" / "v2" / "SKILL.md",
            "---\ndescription: Deep skill\n---\n",
        )
        _, skills, _, _ = _scan_kiro_home(kiro)
        # Parent of SKILL.md is "v2", so name = "v2"
        assert len(skills) == 1
        assert skills[0].name == "v2"

    def test_skill_source_is_kiro_skills(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        _write_text(kiro / "skills" / "my-skill" / "SKILL.md", "---\ndescription: Test\n---\n")
        _, skills, _, _ = _scan_kiro_home(kiro)
        assert skills[0].source == "kiro:skills"


class TestKiroMcpDeduplication:
    def test_duplicate_mcp_names_deduplicated(self, tmp_path: Path):
        """Same MCP name in global settings and agent file — only one entry kept."""
        kiro = tmp_path / ".kiro"
        _write_json(
            kiro / "settings" / "mcp.json",
            {"mcpServers": {"shared-mcp": {"command": "npx", "args": ["shared"]}}},
        )
        _write_json(
            kiro / "agents" / "coder.json",
            {
                "name": "coder",
                "mcpServers": {"shared-mcp": {"command": "npx", "args": ["shared"]}},
            },
        )
        mcps, _, _, _ = _scan_kiro_home(kiro)
        assert len([m for m in mcps if m.name == "shared-mcp"]) == 1

    def test_unique_mcps_all_kept(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"
        _write_json(
            kiro / "settings" / "mcp.json",
            {"mcpServers": {"global-mcp": {"command": "npx", "args": ["g"]}}},
        )
        _write_json(
            kiro / "agents" / "coder.json",
            {"name": "coder", "mcpServers": {"agent-mcp": {"command": "npx", "args": ["a"]}}},
        )
        mcps, _, _, _ = _scan_kiro_home(kiro)
        names = {m.name for m in mcps}
        assert "global-mcp" in names
        assert "agent-mcp" in names


class TestKiroCombinedScan:
    def test_all_types_discovered_together(self, tmp_path: Path):
        kiro = tmp_path / ".kiro"

        # MCP
        _write_json(
            kiro / "settings" / "mcp.json",
            {"mcpServers": {"global-mcp": {"command": "npx", "args": ["g"]}}},
        )
        # Agent with embedded MCP + hook
        _write_json(
            kiro / "agents" / "coder.json",
            {
                "name": "coder",
                "description": "Coding agent",
                "model": "claude-sonnet-4",
                "prompt": "You code.",
                "mcpServers": {"agent-mcp": {"command": "uvx", "args": ["a"]}},
                "hooks": {"preToolUse": [{"command": "echo pre"}]},
            },
        )
        # Skill
        _write_text(
            kiro / "skills" / "react-helper" / "SKILL.md",
            "---\ndescription: React helper\ntask_type: frontend\n---\n",
        )

        mcps, skills, hooks, agents = _scan_kiro_home(kiro)

        assert len(agents) == 1
        assert agents[0].name == "coder"

        mcp_names = {m.name for m in mcps}
        assert "global-mcp" in mcp_names
        assert "agent-mcp" in mcp_names

        assert len(skills) == 1
        assert skills[0].name == "react-helper"
        assert skills[0].task_type == "frontend"

        assert len(hooks) == 1
        assert hooks[0].event == "preToolUse"
