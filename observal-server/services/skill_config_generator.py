# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import re

from schemas.ide_registry import IDE_REGISTRY

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


def _short_description(desc: str, max_len: int = 200) -> str:
    """Extract a single-line summary from a potentially multi-line description.

    Takes the first line of desc. If that line is too long (> max_len), falls
    back to the first sentence (up to first '.'). Strips leading '# ' markdown
    heading markers.
    """
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


def _sanitize_name(name: str) -> str:
    if _SAFE_NAME.match(name):
        return name
    return re.sub(r"[^a-zA-Z0-9_-]", "-", name)


def _generate_skill_file(skill_listing, ide: str, scope: str = "project") -> dict | None:
    """Generate an IDE-specific skill file dict with path and content.

    Returns None for monolithic IDEs (gemini, codex, copilot) that inline
    skills into their rules markdown.
    """
    ide_key = ide.replace("_", "-")
    spec = IDE_REGISTRY.get(ide_key, {})
    skill_paths = spec.get("skill_file")
    if not skill_paths:
        return None

    name = _sanitize_name(skill_listing.name)
    desc = getattr(skill_listing, "description", "") or ""
    slash_cmd = getattr(skill_listing, "slash_command", None)
    path = skill_paths.get(scope, next(iter(skill_paths.values()))).format(name=name)

    short_desc = _short_description(desc)
    skill_format = spec.get("skill_format")
    if skill_format == "yaml_frontmatter":
        content = f"---\nname: {name}\n"
        if short_desc:
            content += f'description: "{short_desc}"\n'
        if slash_cmd and ide_key == "claude-code":
            content += f"command: /{slash_cmd}\n"
        content += f"---\n\n{desc}\n"
    else:
        content = f"---\ndescription: {short_desc}\nalwaysApply: false\n---\n\n# {name}\n\n{desc}\n"

    return {"path": path, "content": content}


def generate_skill_config(
    skill_listing,
    ide: str,
    server_url: str = "http://localhost:8000",
    scope: str = "project",
) -> dict:
    """Generate config snippet for skill install: telemetry hooks + skill file."""
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

    # For Kiro, also include the skill path for auto-loading
    git_url = getattr(skill_listing, "git_url", None)
    if git_url:
        config["skill"]["git_url"] = git_url
    skill_path = getattr(skill_listing, "skill_path", None)
    if skill_path:
        config["skill"]["skill_path"] = skill_path

    # Generate IDE-specific skill file
    skill_file = _generate_skill_file(skill_listing, ide, scope)
    if skill_file:
        config["skill_file"] = skill_file

    return config
