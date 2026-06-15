# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Skill installer - installs bundled Observal skills to detected IDEs."""

from pathlib import Path

from rich import print as rprint


def install_observal_skill():
    """Install the bundled Observal skills to all detected IDE skill directories.

    This makes the 'observal' family of skills available to LLMs in every IDE
    that supports skills, enabling commands like `/observal create an agent` or
    `kiro-cli chat --agent observal`.
    """
    import json as _json

    from observal_cli.ide_registry import IDE_REGISTRY

    skills_base = Path(__file__).parent / "skills"
    skill_dirs = [
        "observal",
        "observal-agents",
        "observal-registry",
        "observal-ops",
        "observal-admin",
        "observal-advanced",
    ]

    # Verify at least the core skill exists.
    core_skill = skills_base / "observal" / "SKILL.md"
    if not core_skill.exists():
        return

    installed: list[str] = []

    for _ide, spec in IDE_REGISTRY.items():
        skill_file_spec = spec.get("skill_file") or {}

        # Install to user scope (global)
        user_path = skill_file_spec.get("user")
        if not user_path:
            continue

        # Only install if the IDE directory exists (IDE is installed)
        ide_config_dir = Path.home() / spec.get("config_dir", "")
        if not ide_config_dir.exists():
            continue

        ide_installed = False
        for skill_dir in skill_dirs:
            source = skills_base / skill_dir / "SKILL.md"
            if not source.exists():
                continue
            resolved = user_path.replace("{name}", skill_dir)
            dest = Path(resolved.replace("~", str(Path.home())))
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                ide_installed = True
            except OSError:
                pass

        if ide_installed:
            installed.append(spec["display_name"])

    # Kiro-specific: ensure the active agent has skill resources wired up.
    # Without this, skills in ~/.kiro/skills/ are invisible to the agent.
    _kiro_skill_resource = "skill://~/.kiro/skills/*/SKILL.md"
    kiro_settings = Path.home() / ".kiro" / "settings" / "cli.json"
    if kiro_settings.exists():
        try:
            settings_data = _json.loads(kiro_settings.read_text())
            active_agent = settings_data.get("chat.defaultAgent", "")
            if active_agent:
                agent_file = Path.home() / ".kiro" / "agents" / f"{active_agent}.json"
                if agent_file.exists():
                    agent_data = _json.loads(agent_file.read_text())
                    resources = agent_data.get("resources", [])
                    if _kiro_skill_resource not in resources:
                        resources.append(_kiro_skill_resource)
                        agent_data["resources"] = resources
                        agent_file.write_text(_json.dumps(agent_data, indent=2) + "\n")
        except (OSError, _json.JSONDecodeError):
            pass

    if installed:
        rprint(f"\n[green]✓ Observal skill installed for:[/green] {', '.join(installed)}")
        rprint('[dim]  LLMs can now use Observal commands directly (e.g. "create a PR agent for kiro")[/dim]')
