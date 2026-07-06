# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for agent_builder._build_skills() — verbatim vs stub paths."""

from __future__ import annotations

import pytest

from services.agent_builder import (
    AgentManifest,
    ManifestComponent,
    ManifestComponents,
    _build_skills,
    generate_harness_agent_profiles,
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
        files = _build_skills(manifest, "claude-code")
        assert len(files) == 1
        assert files[0].content == VERBATIM_MD

    def test_kiro_uses_verbatim(self):
        manifest = _skill_manifest(skill_md_content=VERBATIM_MD)
        files = _build_skills(manifest, "kiro")
        assert len(files) == 1
        assert files[0].content == VERBATIM_MD

    def test_cursor_uses_verbatim(self):
        manifest = _skill_manifest(skill_md_content=VERBATIM_MD)
        files = _build_skills(manifest, "cursor")
        assert len(files) == 1
        assert files[0].content == VERBATIM_MD


class TestBuildSkillFilesFallbackPath:
    def test_claude_code_fallback_has_frontmatter(self):
        manifest = _skill_manifest()  # no skill_md_content
        files = _build_skills(manifest, "claude-code")
        assert len(files) == 1
        content = files[0].content
        assert "name: code-review" in content
        assert "command: /review" in content

    def test_cursor_fallback_has_yaml_frontmatter(self):
        manifest = _skill_manifest()
        files = _build_skills(manifest, "cursor")
        assert len(files) == 1
        assert "name: code-review" in files[0].content

    def test_all_harnesses_produce_skills(self):
        """All harnesses have skill entries and produce output."""
        manifest = _skill_manifest(skill_md_content=VERBATIM_MD)
        for harness in ("codex", "copilot", "cursor", "claude-code", "kiro"):
            assert _build_skills(manifest, harness) != [], f"{harness} should produce skill files"


class TestSkillFilePaths:
    @pytest.mark.parametrize(
        "harness,expected_prefix",
        [
            ("claude-code", ".claude/skills/"),
            ("kiro", ".kiro/skills/"),
            ("cursor", ".cursor/skills/"),
        ],
    )
    def test_skill_path(self, harness: str, expected_prefix: str):
        manifest = _skill_manifest(skill_md_content=VERBATIM_MD)
        files = _build_skills(manifest, harness)
        assert len(files) == 1
        assert files[0].path.startswith(expected_prefix) or files[0].path.startswith(
            "~/" + expected_prefix.lstrip("./")
        )


class TestGenerateHarnessAgentFilesWithSkills:
    @pytest.mark.parametrize(
        "harness",
        ["claude-code", "cursor", "kiro", "opencode", "codex", "copilot"],
    )
    def test_skill_in_harness_output(self, harness: str):
        manifest = _skill_manifest(skill_md_content=VERBATIM_MD)
        config = generate_harness_agent_profiles(manifest, harness)
        # The verbatim content uniquely identifies the skill file regardless of path.
        skills = [f for f in config.files if f.content == VERBATIM_MD]
        assert len(skills) == 1
