# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Consolidated skill file builder.

Provides a single source of truth for generating harness-specific skill files,
used by both the agent_builder (manifest-based) and the harness config generator
(registry-based with live DB listings).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from schemas.harness_registry import HARNESS_REGISTRY
from schemas.skill_commands import normalize_slash_command
from services.shared.utils import sanitize_name as _sanitize_name
from services.skill_validator import validate_skill_md_content_frontmatter

if TYPE_CHECKING:
    from services.agent_builder_types import AgentFile, AgentManifest


def _yaml_frontmatter(data: dict[str, str | bool]) -> str:
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True).strip()
    return f"---\n{body}\n---\n\n"


def generate_skill(skill: dict, harness: str, scope: str = "project") -> dict | None:
    """Generate an harness-specific skill file entry.

    Returns a dict with 'path' and 'content' keys, or None for
    monolithic harnesses (Gemini, Codex, Copilot) that inline skills into rules.

    This is the canonical implementation used by both code paths.
    """
    harness_key = harness.replace("_", "-")
    spec = HARNESS_REGISTRY.get(harness_key, {})
    skill_paths = spec.get("skills")
    if not skill_paths:
        return None

    name = skill["name"]
    desc = skill.get("description", "")
    slash_cmd = skill.get("slash_command")
    path = skill_paths.get(scope, next(iter(skill_paths.values()))).format(name=name)

    skill_format = spec.get("skill_format")
    if skill_format == "yaml_frontmatter":
        frontmatter = {"name": name}
        if desc:
            frontmatter["description"] = desc
        if slash_cmd and harness_key == "claude-code":
            frontmatter["command"] = f"/{normalize_slash_command(slash_cmd)}"
        content = _yaml_frontmatter(frontmatter) + f"{desc}\n"
    else:
        frontmatter = {"description": desc, "alwaysApply": False}
        content = _yaml_frontmatter(frontmatter) + f"# {name}\n\n{desc}\n"

    return {"path": path, "content": content}


def build_skills(manifest: AgentManifest, harness: str) -> list[AgentFile]:
    """Generate harness-specific skill files from manifest skills.

    Fast path: if skill_md_content is cached (stored verbatim from the repo),
    use it as-is as the SKILL.md body. Fallback: synthesize a minimal stub
    from description + slash_command.

    This is the manifest-based path used by the agent builder.
    """
    from services.agent_builder_types import AgentFile

    harness_key = harness.replace("_", "-")
    spec = HARNESS_REGISTRY.get(harness_key, {})
    skill_paths = spec.get("skills")
    if not skill_paths:
        return []

    files: list[AgentFile] = []
    skill_format = spec.get("skill_format")
    for skill in manifest.components.skills:
        name = _sanitize_name(skill.name)
        desc = skill.description or ""
        path = next(iter(skill_paths.values())).format(name=name)

        # Fast path: verbatim SKILL.md from git repo
        skill_md_content: str | None = (skill.config_override or {}).get("skill_md_content")
        if skill_md_content:
            validate_skill_md_content_frontmatter(skill_md_content, slash_command=skill.slash_command)
            files.append(AgentFile(path=path, content=skill_md_content, format="markdown"))
            continue

        # Fallback: synthetic stub
        if skill_format == "yaml_frontmatter":
            frontmatter = {"name": name}
            if desc:
                frontmatter["description"] = desc
            if skill.slash_command and harness_key == "claude-code":
                frontmatter["command"] = f"/{normalize_slash_command(skill.slash_command)}"
            content = _yaml_frontmatter(frontmatter) + f"{desc}\n"
        else:
            frontmatter = {"description": desc, "alwaysApply": False}
            content = _yaml_frontmatter(frontmatter) + f"# {name}\n\n{desc}\n"

        files.append(AgentFile(path=path, content=content, format="markdown"))

    return files
