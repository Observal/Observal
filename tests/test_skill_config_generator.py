# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for skill_config_generator — IDE-specific skill file generation."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from services.skill_config_generator import (
    _generate_skill_file,
    _sanitize_name,
    generate_skill_config,
)


def _make_skill_listing(
    name: str = "code-review",
    description: str = "Automated code review skill",
    slash_command: str | None = "review",
    git_url: str = "https://github.com/org/skills.git",
    skill_path: str = "skills/code-review",
) -> MagicMock:
    listing = MagicMock()
    listing.id = uuid.uuid4()
    listing.name = name
    listing.description = description
    listing.slash_command = slash_command
    listing.git_url = git_url
    listing.skill_path = skill_path
    return listing


class TestSanitizeName:
    def test_safe_name_passthrough(self):
        assert _sanitize_name("my-skill_v2") == "my-skill_v2"

    def test_unsafe_chars_replaced(self):
        assert _sanitize_name("my skill!") == "my-skill-"

    def test_dots_replaced(self):
        assert _sanitize_name("v1.2.3") == "v1-2-3"


class TestGenerateSkillFile:
    def test_claude_code_project_scope(self):
        listing = _make_skill_listing()
        result = _generate_skill_file(listing, "claude-code", scope="project")
        assert result is not None
        assert result["path"] == ".claude/skills/code-review/SKILL.md"
        assert "name: code-review" in result["content"]
        assert 'description: "Automated code review skill"' in result["content"]
        assert "command: /review" in result["content"]

    def test_claude_code_user_scope(self):
        listing = _make_skill_listing()
        result = _generate_skill_file(listing, "claude-code", scope="user")
        assert result["path"] == "~/.claude/skills/code-review/SKILL.md"

    def test_kiro(self):
        listing = _make_skill_listing()
        result = _generate_skill_file(listing, "kiro")
        assert result is not None
        assert result["path"] == ".kiro/skills/code-review/SKILL.md"
        assert "name: code-review" in result["content"]

    def test_cursor_project_scope(self):
        listing = _make_skill_listing()
        result = _generate_skill_file(listing, "cursor", scope="project")
        assert result["path"] == ".cursor/rules/code-review.mdc"
        assert "alwaysApply: false" in result["content"]
        assert "# code-review" in result["content"]

    def test_cursor_user_scope(self):
        listing = _make_skill_listing()
        result = _generate_skill_file(listing, "cursor", scope="user")
        assert result["path"] == "~/.cursor/rules/code-review.mdc"

    def test_vscode(self):
        listing = _make_skill_listing()
        result = _generate_skill_file(listing, "vscode")
        assert result["path"] == ".github/instructions/code-review.instructions.md"
        assert "alwaysApply: false" in result["content"]

    def test_monolithic_ide_returns_none(self):
        listing = _make_skill_listing()
        assert _generate_skill_file(listing, "codex") is None
        assert _generate_skill_file(listing, "copilot") is None

    def test_no_slash_command(self):
        listing = _make_skill_listing(slash_command=None)
        result = _generate_skill_file(listing, "claude-code")
        assert "command:" not in result["content"]

    def test_no_description(self):
        listing = _make_skill_listing(description="")
        result = _generate_skill_file(listing, "claude-code")
        assert "description:" not in result["content"]


class TestGenerateSkillConfig:
    def test_includes_hooks(self):
        listing = _make_skill_listing()
        config = generate_skill_config(listing, "claude-code")
        assert "hooks" in config
        assert "SessionStart" in config["hooks"]
        assert "SessionEnd" in config["hooks"]

    def test_includes_skill_file_for_claude_code(self):
        listing = _make_skill_listing()
        config = generate_skill_config(listing, "claude-code")
        assert "skill_file" in config
        assert config["skill_file"]["path"] == ".claude/skills/code-review/SKILL.md"

    def test_includes_skill_file_for_kiro(self):
        listing = _make_skill_listing()
        config = generate_skill_config(listing, "kiro")
        assert "skill_file" in config
        assert config["skill_file"]["path"] == ".kiro/skills/code-review/SKILL.md"

    def test_no_skill_file_for_codex(self):
        listing = _make_skill_listing()
        config = generate_skill_config(listing, "codex")
        assert "skill_file" not in config

    def test_scope_user(self):
        listing = _make_skill_listing()
        config = generate_skill_config(listing, "claude-code", scope="user")
        assert config["skill_file"]["path"].startswith("~/.claude/")

    def test_git_url_included(self):
        listing = _make_skill_listing()
        config = generate_skill_config(listing, "claude-code")
        assert config["skill"]["git_url"] == "https://github.com/org/skills.git"

    def test_skill_path_included(self):
        listing = _make_skill_listing()
        config = generate_skill_config(listing, "cursor")
        assert config["skill"]["skill_path"] == "skills/code-review"

    def test_claude_code_allows_env_vars(self):
        listing = _make_skill_listing()
        config = generate_skill_config(listing, "claude-code")
        hook = config["hooks"]["SessionStart"][0]["hooks"][0]
        assert "allowedEnvVars" in hook
