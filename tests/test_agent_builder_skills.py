# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for agent_builder._build_skill_files() — verbatim vs stub paths."""

from __future__ import annotations

import pytest

from services.agent_builder import (
    AgentManifest,
    ManifestComponent,
    ManifestComponents,
    _build_skill_files,
    generate_ide_agent_files,
)


def _skill_manifest(
    skill_name: str = "code-review",
    description: str = "Reviews your code",
    slash_command: str | None = "review",
    skill_md_content: str | None = None,
) -> AgentManifest:
    skill = ManifestComponent(
        name=skill_name,
        version="1.0.0",
        description=description,
        slash_command=slash_command,
        config_override={"skill_md_content": skill_md_content} if skill_md_content else None,
    )
    return AgentManifest(
        name="test-agent",
        version="1.0.0",
        prompt="Do stuff",
        components=ManifestComponents(skills=[skill]),
    )


VERBATIM_MD = """\
---
name: code-review
description: Real skill content from the git repo
command: /review
---

## Instructions

Actually review the code properly.

## Rules

- Check for bugs
- Check style
"""


class TestBuildSkillFilesVerbatimPath:
    def test_claude_code_uses_verbatim(self):
        manifest = _skill_manifest(skill_md_content=VERBATIM_MD)
        files = _build_skill_files(manifest, "claude-code")
        assert len(files) == 1
        assert files[0].content == VERBATIM_MD

    def test_kiro_uses_verbatim(self):
        manifest = _skill_manifest(skill_md_content=VERBATIM_MD)
        files = _build_skill_files(manifest, "kiro")
        assert len(files) == 1
        assert files[0].content == VERBATIM_MD

    def test_cursor_uses_verbatim(self):
        manifest = _skill_manifest(skill_md_content=VERBATIM_MD)
        files = _build_skill_files(manifest, "cursor")
        assert len(files) == 1
        assert files[0].content == VERBATIM_MD


class TestBuildSkillFilesFallbackPath:
    def test_claude_code_fallback_has_frontmatter(self):
        manifest = _skill_manifest()  # no skill_md_content
        files = _build_skill_files(manifest, "claude-code")
        assert len(files) == 1
        content = files[0].content
        assert "name: code-review" in content
        assert "command: /review" in content

    def test_cursor_fallback_has_yaml_frontmatter(self):
        manifest = _skill_manifest()
        files = _build_skill_files(manifest, "cursor")
        assert len(files) == 1
        assert "name: code-review" in files[0].content

    def test_all_ides_produce_skill_files(self):
        """All IDEs have skill_file entries and produce output."""
        manifest = _skill_manifest(skill_md_content=VERBATIM_MD)
        for ide in ("codex", "copilot", "cursor", "claude-code", "kiro"):
            assert _build_skill_files(manifest, ide) != [], f"{ide} should produce skill files"


class TestSkillFilePaths:
    @pytest.mark.parametrize(
        "ide,expected_prefix",
        [
            ("claude-code", ".claude/skills/"),
            ("kiro", ".kiro/skills/"),
            ("cursor", ".cursor/skills/"),
        ],
    )
    def test_skill_file_path(self, ide: str, expected_prefix: str):
        manifest = _skill_manifest(skill_md_content=VERBATIM_MD)
        files = _build_skill_files(manifest, ide)
        assert len(files) == 1
        assert files[0].path.startswith(expected_prefix) or files[0].path.startswith(
            "~/" + expected_prefix.lstrip("./")
        )


class TestGenerateIdeAgentFilesWithSkills:
    @pytest.mark.parametrize(
        "ide",
        ["claude-code", "cursor", "kiro", "opencode", "codex", "copilot"],
    )
    def test_skill_file_in_ide_output(self, ide: str):
        manifest = _skill_manifest(skill_md_content=VERBATIM_MD)
        config = generate_ide_agent_files(manifest, ide)
        # The verbatim content uniquely identifies the skill file regardless of path.
        skill_files = [f for f in config.files if f.content == VERBATIM_MD]
        assert len(skill_files) == 1
