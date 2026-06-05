# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import re

import yaml
from loguru import logger as optic

from schemas.ide_registry import IDE_REGISTRY
from schemas.skill_commands import normalize_slash_command
from services.shared.utils import sanitize_name as _sanitize_name
from services.skill_validator import validate_skill_md_content_frontmatter


def _yaml_frontmatter(data: dict[str, str]) -> str:
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True).strip()
    return f"---\n{body}\n---\n\n"


def _short_description(desc: str, max_len: int = 200) -> str:
    """Extract a single-line summary from a potentially multi-line description.

    Takes the first line of desc. If that line is too long (> max_len), falls
    back to the first sentence (up to first '.'). Strips leading '# ' markdown
    heading markers.
    """
    optic.trace("truncating description to {} chars", max_len)
    if not desc:
        return ""
    first_line = desc.split("\n", 1)[0].strip()
    # Strip leading markdown heading markers (e.g. "# ", "## ")
    first_line = re.sub(r"^#+\s*", "", first_line)
    if len(first_line) <= max_len:
        return first_line
    # Fall back to first sentence
    sentence, _, _ = first_line.partition(".")
    return sentence.strip()


def _generate_skill_file(skill_source, ide: str, scope: str = "project") -> dict | None:
    """Generate an IDE-specific skill file dict with path and content.

    skill_source can be a SkillListing or SkillVersion (both have skill_md_content).
    Returns None for monolithic IDEs (gemini, codex, copilot) that inline
    skills into their rules markdown.
    """
    name_attr = getattr(skill_source, "name", None)
    # SkillVersion doesn't have .name, get it from the listing relationship
    if not name_attr and hasattr(skill_source, "listing"):
        name_attr = getattr(skill_source.listing, "name", "skill")
    if not name_attr:
        name_attr = "skill"
    optic.debug("generating skill config for {} (ide={}, scope={})", name_attr, ide, scope)
    ide_key = ide.replace("_", "-")
    spec = IDE_REGISTRY.get(ide_key, {})
    skill_paths = spec.get("skill_file")
    if not skill_paths:
        return None

    name = _sanitize_name(name_attr)
    desc = getattr(skill_source, "description", "") or ""
    slash_cmd = getattr(skill_source, "slash_command", None)
    path = skill_paths.get(scope, next(iter(skill_paths.values()))).format(name=name)

    # Fast path: verbatim SKILL.md cached from the git repo.
    skill_md_content = getattr(skill_source, "skill_md_content", None)
    if skill_md_content:
        validate_skill_md_content_frontmatter(skill_md_content, slash_command=slash_cmd)
        return {"path": path, "content": skill_md_content}

    # Fallback: synthesise a minimal stub from stored fields.
    short_desc = _short_description(desc)
    skill_format = spec.get("skill_format")
    if skill_format == "yaml_frontmatter":
        frontmatter = {"name": name}
        if short_desc:
            frontmatter["description"] = short_desc
        if slash_cmd and ide_key == "claude-code":
            frontmatter["command"] = f"/{normalize_slash_command(slash_cmd)}"
        content = _yaml_frontmatter(frontmatter) + f"{desc}\n"
    else:
        frontmatter = {"description": short_desc, "alwaysApply": False}
        content = _yaml_frontmatter(frontmatter) + f"# {name}\n\n{desc}\n"

    return {"path": path, "content": content}


def generate_skill_config(
    skill_listing,
    ide: str,
    server_url: str = "http://localhost:8000",
    scope: str = "project",
    version_override=None,
) -> dict:
    """Generate config snippet for skill install: telemetry hooks + skill file.

    If version_override is provided, uses content from that specific version
    instead of the listing's latest content.
    """
    optic.trace("generating skill frontmatter for {} on {}", skill_listing.name, ide)
    skill_id = str(skill_listing.id)
    skill_name = str(skill_listing.name)

    hook_entry = {
        "type": "http",
        "url": f"{server_url}/api/v1/telemetry/hooks",
        "headers": {
            "Authorization": "Bearer $OBSERVAL_ACCESS_TOKEN",
            "X-Observal-Skill-Id": skill_id,
        },
        "timeout": 10,
    }
    if ide == "claude-code":
        hook_entry["allowedEnvVars"] = ["OBSERVAL_ACCESS_TOKEN"]

    config = {
        "hooks": {
            "SessionStart": [{"matcher": "*", "hooks": [hook_entry]}],
            "SessionEnd": [{"matcher": "*", "hooks": [hook_entry]}],
        },
        "skill": {"name": skill_name, "id": skill_id},
        "ide": ide,
        "listing_id": skill_id,
    }

    # Always include git coordinates - they are the install-time source of truth.
    # When a specific version is requested, use its content over the listing's.
    source = version_override if version_override else skill_listing

    git_url = getattr(source, "git_url", None) or getattr(skill_listing, "git_url", None)
    if git_url:
        config["skill"]["git_url"] = git_url
    skill_path = getattr(source, "skill_path", None) or getattr(skill_listing, "skill_path", None)
    if skill_path:
        config["skill"]["skill_path"] = skill_path
    git_ref = getattr(source, "git_ref", None) or getattr(skill_listing, "git_ref", None)
    if git_ref:
        config["skill"]["git_ref"] = git_ref
    # Cache skill_md_content as a fast-path fallback (no git needed at install time).
    skill_md_content = getattr(source, "skill_md_content", None)
    if skill_md_content:
        validate_skill_md_content_frontmatter(
            skill_md_content, slash_command=getattr(skill_listing, "slash_command", None)
        )
        config["skill"]["skill_md_content"] = skill_md_content

    # Delivery mode and registry-direct script
    delivery_mode = getattr(source, "delivery_mode", None) or getattr(skill_listing, "delivery_mode", "git_fetch")
    config["skill"]["delivery_mode"] = delivery_mode
    if delivery_mode == "registry_direct":
        script_content = getattr(source, "script_content", None)
        script_filename = getattr(source, "script_filename", None)
        if script_content:
            config["skill"]["script_content"] = script_content
        if script_filename:
            config["skill"]["script_filename"] = script_filename

    # Include version info in the response
    if version_override:
        config["skill"]["version"] = getattr(version_override, "version", None)
        config["skill"]["latest_version"] = getattr(skill_listing, "version", None)

    # Generate IDE-specific skill file
    skill_file = _generate_skill_file(source, ide, scope)
    if skill_file:
        config["skill_file"] = skill_file

    return config
