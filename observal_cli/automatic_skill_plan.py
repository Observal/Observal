# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Exact owned-file plan for a single registry-direct, user-scoped Pi skill.

The normal skill installer remains the only writer. This module supplies its
pre-write evidence; Git trees, scripts and ambiguous destinations have no plan.
"""

from __future__ import annotations

from pathlib import Path

from observal_cli import install_baseline, lockfile
from observal_cli.shared.utils import sanitize_name


class SkillPlanError(ValueError):
    """This skill needs a manual install."""


def identity(component_id: str) -> str:
    # Baseline keys predate component ownership; namespace standalone skills
    # separately from agents with the same registry UUID.
    return f"skill:{component_id}"


def release_key(version: str, digest: str | None, version_id: str | None) -> str:
    return f"skill:{version}:{digest or ''}:{version_id or ''}"


def destination(name: str) -> Path:
    return Path.home() / ".pi" / "agent" / "skills" / sanitize_name(name)


def single_file(root: Path) -> Path:
    """Reject any directory content not covered by the single-file writer."""
    if not root.is_absolute() or any(part.is_symlink() for part in (root, *root.parents)) or not root.is_dir():
        raise SkillPlanError("The Pi skill destination is missing or crosses a link; update manually.")
    if {p.name for p in root.iterdir()} != {"SKILL.md"} or not (root / "SKILL.md").is_file():
        raise SkillPlanError("The Pi skill has extra or missing files; update manually.")
    file = root / "SKILL.md"
    if file.is_symlink():
        raise SkillPlanError("The Pi skill file is linked; update manually.")
    return file


def unshared(registry: str, component_id: str, name: str) -> None:
    """The lockfile may contain another owner even without its own baseline."""
    from observal_cli.lockfile import normalize_server_url

    target_name = sanitize_name(name)
    try:
        data = lockfile.read_lockfile()
        for url, section in data.get("registries", {}).items():
            for entry in section.get("harnesses", {}).get("pi", {}).get("standalone", []):
                if entry.get("type") != "skill" or entry.get("scope") != "user":
                    continue
                # The normal installer writes using the registry-provided
                # local_name, which can differ from the lockfile display name.
                # Older entries may have only the display name. Neither entry
                # needs its own baseline to claim the destination.
                local_name = entry.get("local_name")
                display_name = entry.get("name")
                if (
                    (isinstance(local_name, str) and sanitize_name(local_name) == target_name)
                    or (isinstance(display_name, str) and sanitize_name(display_name) == target_name)
                ) and (normalize_server_url(url) != normalize_server_url(registry) or entry.get("id") != component_id):
                    raise SkillPlanError("Another installed skill uses this Pi path; update manually.")
    except (OSError, RuntimeError, TypeError, KeyError) as error:
        raise SkillPlanError("Skill ownership cannot be checked; update manually.") from error


def verified_path(item: dict, *, registry: str) -> Path:
    if item.get("type") != "skill" or item.get("harness") != "pi" or item.get("scope") != "user":
        raise SkillPlanError("Only user-scoped Pi skills can be updated automatically.")
    if item.get("pin_known") is not True or item.get("requested_version"):
        raise SkillPlanError("Skill pin intent is unknown or explicitly pinned; update manually.")
    name = item.get("name")
    local_name = item.get("local_name")
    if not isinstance(name, str) or not isinstance(local_name, str) or sanitize_name(name) != local_name:
        raise SkillPlanError("The installed skill destination is ambiguous; update manually.")
    unshared(registry, item["id"], name)
    root = destination(name)
    file = single_file(root)
    files, paths = install_baseline.verified_manifest(
        registry=registry,
        harness="pi",
        agent_id=identity(item["id"]),
        scope="user",
        root=str(root),
        version=item["current_version"],
        lock_digest=release_key(item["current_version"], item.get("digest"), item.get("version_id")),
    )
    if paths != [str(file)] or set(files) != {str(file)}:
        raise SkillPlanError("The skill ownership plan contains other files; update manually.")
    return file


def target(item: dict, skill: dict, file: Path) -> bytes:
    """Check the install response against the normal writer's exact output."""
    content = skill.get("skill_md_content")
    name = skill.get("name")
    if (
        skill.get("delivery_mode") != "registry_direct"
        or not isinstance(content, str)
        or not content
        or not isinstance(name, str)
        or sanitize_name(name) != item.get("local_name")
        or file != destination(name) / "SKILL.md"
        or skill.get("script_content")
        or skill.get("script_filename")
        or skill.get("git_url")
    ):
        raise SkillPlanError("The release changes the skill path, source or file set; update manually.")
    raw = content.encode("utf-8")
    if len(raw) + file.stat().st_size > 2 * 1024 * 1024:
        raise SkillPlanError("The skill exceeds the recovery size limit; update manually.")
    return raw
