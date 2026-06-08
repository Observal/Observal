# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""observal doctor: diagnose and patch IDE settings for Observal session telemetry.

Supports Claude Code and Kiro.  Injects 2 hooks (UserPromptSubmit + Stop) that
push session JSONL incrementally to the server.
"""

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import typer
from loguru import logger as optic
from rich import print as rprint

from observal_cli import config
from observal_cli.ide_registry import get_home_mcp_configs, get_mcp_servers_key, get_valid_ides
from observal_cli.ide_specs.claude_code_hooks_spec import (
    MANAGED_ENV_KEYS,
    get_desired_hooks,
)
from observal_cli.shared.utils import (
    is_already_shimmed as _is_already_shimmed,
)
from observal_cli.shared.utils import (
    is_observal_hook_entry as _is_observal_hook_entry,
)
from observal_cli.shared.utils import (
    is_observal_matcher_group as _is_observal_matcher_group,
)
from observal_cli.shared.utils import (
    load_jsonc as _load_jsonc,
)

doctor_app = typer.Typer(help="Diagnose and patch IDE settings for Observal telemetry")


# ── Helpers ──────────────────────────────────────────────────


def _load_json(path: Path) -> dict | None:
    optic.trace("path={}", path)
    try:
        return _load_jsonc(path)
    except Exception:
        return None


# ── Diagnose command ─────────────────────────────────────────


@doctor_app.callback(invoke_without_command=True)
def doctor(
    ctx: typer.Context, yes: bool = typer.Option(False, "--yes", "-y", help="Auto-fix all issues without prompting")
):
    """Diagnose IDE settings and offer to configure telemetry + AI skill."""
    if ctx.invoked_subcommand is not None:
        return

    issues: list[str] = []
    warnings: list[str] = []

    rprint("[bold]Observal Doctor[/bold]\n")

    # 1. Check Observal config
    rprint("[cyan]Checking Observal config...[/cyan]")
    _check_observal_config(issues, warnings)

    # 2. Check Claude Code
    rprint("[cyan]Checking Claude Code...[/cyan]")
    _check_claude_code(issues, warnings)

    # 3. Check Kiro
    rprint("[cyan]Checking Kiro...[/cyan]")
    _check_kiro(issues, warnings)

    # 4. Check Pi
    rprint("[cyan]Checking Pi...[/cyan]")
    _check_pi(issues, warnings)

    # 5. Check Cursor
    rprint("[cyan]Checking Cursor...[/cyan]")
    _check_cursor(issues, warnings)

    # 6. Check Codex
    rprint("[cyan]Checking Codex...[/cyan]")
    _check_codex(issues, warnings)

    # 7. Check Copilot (VS Code)
    rprint("[cyan]Checking Copilot (VS Code)...[/cyan]")
    _check_copilot(issues, warnings)

    # 8. Check Copilot CLI
    rprint("[cyan]Checking Copilot CLI...[/cyan]")
    _check_copilot_cli(issues, warnings)

    # 9. Check OpenCode
    rprint("[cyan]Checking OpenCode...[/cyan]")
    _check_opencode(issues, warnings)

    # 10. Check if observal skill is installed
    skill_missing = _check_observal_skill_missing()
    if skill_missing:
        warnings.append(
            f"Observal AI skill not installed for: {', '.join(skill_missing)}. "
            "LLMs won't have /observal commands available."
        )

    # Report
    rprint("")
    if not issues and not warnings:
        rprint("[bold green]All clear![/bold green] No issues found.")
        raise typer.Exit(0)

    if issues:
        rprint(f"[bold red]{len(issues)} issue(s):[/bold red]")
        for i, issue in enumerate(issues, 1):
            rprint(f"  [red]{i}.[/red] {issue}")

    if warnings:
        rprint(f"\n[bold yellow]{len(warnings)} warning(s):[/bold yellow]")
        for i, warning in enumerate(warnings, 1):
            rprint(f"  [yellow]{i}.[/yellow] {warning}")

    # Offer to fix everything in one go
    fixable = len(warnings) > 0
    should_fix = yes
    if fixable and not yes and sys.stdin.isatty():
        rprint("")
        should_fix = typer.confirm(
            "Fix all issues? (configures telemetry + installs AI skill for all detected IDEs)", default=True
        )
    if fixable and should_fix:
        import subprocess

        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        subprocess.run(
            [sys.executable, "-m", "observal_cli.main", "doctor", "patch", "--all", "--all-ides"],
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=env,
        )
        # Install the observal skill
        from observal_cli.skill_installer import install_observal_skill

        install_observal_skill()
    elif fixable and not should_fix:
        rprint("[dim]  Run [bold]observal doctor patch --all --all-ides[/bold] anytime to fix.[/dim]")

    raise typer.Exit(1 if issues else 0)


def _check_observal_skill_missing() -> list[str]:
    """Return list of IDE display names where the observal skill is not installed."""
    from observal_cli.ide_registry import IDE_REGISTRY

    skill_source = Path(__file__).parent / "skills" / "observal" / "SKILL.md"
    if not skill_source.exists():
        return []

    _extra_user_paths: dict[str, str] = {"kiro": "~/.kiro/skills/{name}/SKILL.md"}
    missing: list[str] = []

    for ide, spec in IDE_REGISTRY.items():
        skill_file_spec = spec.get("skill_file") or {}
        user_path = skill_file_spec.get("user") or _extra_user_paths.get(ide)
        if not user_path:
            continue

        resolved = user_path.replace("{name}", "observal")
        dest = Path(resolved.replace("~", str(Path.home())))
        ide_config_dir = Path.home() / spec.get("config_dir", "")
        if not ide_config_dir.exists():
            continue

        if not dest.exists():
            missing.append(spec["display_name"])

    return missing


def _check_observal_config(issues: list, warnings: list):
    optic.trace("issues={}, warnings={}", issues, warnings)
    config_path = Path.home() / ".observal" / "config.json"
    if not config_path.exists():
        issues.append("~/.observal/config.json not found. Run `observal auth login` first.")
        return

    data = _load_json(config_path)
    if data is None:
        issues.append("~/.observal/config.json is not valid JSON.")
        return

    if not data.get("access_token"):
        issues.append("No access token in ~/.observal/config.json. Run `observal auth login`.")

    if not data.get("server_url"):
        issues.append("No server_url in ~/.observal/config.json. Run `observal auth login`.")

    server_url = data.get("server_url", "")
    if server_url:
        try:
            import httpx

            resp = httpx.get(f"{server_url}/health", timeout=5)
            if resp.status_code != 200:
                issues.append(f"Observal server at {server_url} returned status {resp.status_code}.")
        except Exception as e:
            issues.append(f"Cannot reach Observal server at {server_url}: {e}")


def _check_claude_code(issues: list, warnings: list):
    optic.trace("issues={}, warnings={}", issues, warnings)
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        rprint("  [dim]No ~/.claude/settings.json found[/dim]")
        return

    data = _load_json(settings_path)
    if data is None:
        issues.append(f"{settings_path}: not valid JSON.")
        return

    if data.get("disableAllHooks"):
        issues.append(f"{settings_path}: `disableAllHooks` is true. Observal hooks will not fire.")

    # Check if session push hooks are installed
    hooks = data.get("hooks", {})
    has_session_push = False
    for event in ("UserPromptSubmit", "Stop"):
        groups = hooks.get(event, [])
        for g in groups:
            for h in g.get("hooks", []):
                if "observal_cli.hooks.session_push" in h.get("command", ""):
                    has_session_push = True
                    break

    if not has_session_push:
        warnings.append(
            "Claude Code session push hooks not installed. "
            "Run `observal doctor patch --all --ide claude-code` to inject them."
        )

    # Check for stale legacy hooks
    has_legacy = False
    for _event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for g in groups:
            for h in g.get("hooks", []):
                cmd = h.get("command", "")
                if any(m in cmd for m in ("observal-hook", "observal-stop-hook", "/api/v1/telemetry/hooks")):
                    has_legacy = True
                    break

    if has_legacy:
        warnings.append(
            "Legacy Observal hooks detected (old hook scripts). "
            "Run `observal doctor cleanup --ide claude-code` to remove them."
        )


def _check_kiro(issues: list, warnings: list):
    optic.trace("issues={}, warnings={}", issues, warnings)
    agents_dir = Path.home() / ".kiro" / "agents"
    if not agents_dir.is_dir():
        rprint("  [dim]No ~/.kiro/agents/ found[/dim]")
        return

    agent_files = list(agents_dir.glob("*.json"))
    if not agent_files:
        rprint("  [dim]No Kiro agent configs found[/dim]")
        return

    has_session_push = False
    for af in agent_files:
        try:
            agent_data = json.loads(af.read_text())
        except Exception:
            continue
        hooks = agent_data.get("hooks", {})
        for _event, entries in hooks.items():
            if not isinstance(entries, list):
                continue
            for h in entries:
                if "observal_cli.hooks.kiro_session_push" in h.get("command", ""):
                    has_session_push = True
                    break

    if not has_session_push:
        warnings.append(
            "Kiro session push hooks not installed in any agent config. "
            "Run `observal doctor patch --all --ide kiro` to inject them."
        )


def _check_pi(issues: list, warnings: list):
    """Check if Observal pi extension is installed."""
    optic.debug("_check_pi")
    pi_dir = Path.home() / ".pi" / "agent"
    if not pi_dir.exists():
        rprint("  [dim]Pi not detected[/dim]")
        return

    settings_path = pi_dir / "settings.json"
    if not settings_path.exists():
        rprint("  [dim]No ~/.pi/agent/settings.json found[/dim]")
        return

    data = _load_json(settings_path)
    if data is None:
        issues.append(f"{settings_path}: not valid JSON.")
        return

    packages = data.get("packages", [])
    has_observal = any("observal-pi" in (p if isinstance(p, str) else p.get("source", "")) for p in packages)

    if not has_observal:
        warnings.append(
            "Observal pi extension not installed. Run `pi install npm:observal-pi` to enable session telemetry."
        )


def _check_cursor(issues: list, warnings: list):
    """Check if Observal session push hooks are installed in Cursor."""
    optic.debug("_check_cursor")
    hooks_path = Path.home() / ".cursor" / "hooks.json"
    if not (Path.home() / ".cursor").exists():
        rprint("  [dim]Cursor not detected[/dim]")
        return

    if not hooks_path.exists():
        warnings.append(
            "Cursor session push hooks not installed. Run `observal doctor patch --all --ide cursor` to inject them."
        )
        return

    data = _load_json(hooks_path)
    if data is None:
        issues.append(f"{hooks_path}: not valid JSON.")
        return

    hooks = data.get("hooks", {})
    has_session_push = False
    for event in ("beforeSubmitPrompt", "stop"):
        entries = hooks.get(event, [])
        for e in entries:
            if "cursor_session_push" in e.get("command", ""):
                has_session_push = True
                break

    if not has_session_push:
        warnings.append(
            "Cursor session push hooks not installed. Run `observal doctor patch --all --ide cursor` to inject them."
        )


def _check_codex(issues: list, warnings: list):
    """Check if Observal session push hooks are installed in Codex."""
    optic.debug("_check_codex")
    codex_dir = Path.home() / ".codex"
    if not codex_dir.exists():
        rprint("  [dim]Codex not detected[/dim]")
        return

    hooks_path = codex_dir / "hooks.json"
    config_path = codex_dir / "config.toml"

    # Check hooks
    has_session_push = False
    if hooks_path.exists():
        data = _load_json(hooks_path)
        if data is not None:
            hooks = data.get("hooks", {})
            for event in ("UserPromptSubmit", "Stop"):
                groups = hooks.get(event, [])
                for g in groups:
                    if isinstance(g, dict):
                        for h in g.get("hooks", []):
                            if isinstance(h, dict) and "codex_session_push" in h.get("command", ""):
                                has_session_push = True
                                break

    if not has_session_push:
        warnings.append(
            "Codex session push hooks not installed. Run `observal doctor patch --all --ide codex` to inject them."
        )

    # Check codex_hooks flag
    if config_path.exists():
        try:
            content = config_path.read_text()
            if "codex_hooks = false" in content:
                issues.append(f"{config_path}: `codex_hooks = false`. Observal hooks will not fire.")
        except OSError:
            pass


def _check_copilot(issues: list, warnings: list):
    """Check if Observal session push hooks are installed for Copilot (VS Code agent mode)."""
    optic.debug("_check_copilot")
    # Copilot VS Code uses project-level hooks in .github/hooks/
    # and user-level hooks in ~/.copilot/hooks/
    user_hooks = Path.home() / ".copilot" / "hooks" / "observal.json"
    project_hooks = Path.cwd() / ".github" / "hooks" / "observal.json"

    # Check if VS Code / Copilot is even present
    has_vscode = (Path.home() / ".vscode").exists()
    if not has_vscode:
        rprint("  [dim]Copilot (VS Code) not detected[/dim]")
        return

    has_hooks = False
    for hooks_path in (user_hooks, project_hooks):
        if hooks_path.exists():
            data = _load_json(hooks_path)
            if data is not None:
                hooks = data.get("hooks", {})
                for entries in hooks.values():
                    if isinstance(entries, list):
                        for e in entries:
                            cmd = e.get("command", "") + e.get("bash", "")
                            if "copilot_vscode_session_push" in cmd or "run_hook.ps1" in cmd:
                                has_hooks = True
                                break

    if not has_hooks:
        warnings.append(
            "Copilot (VS Code) session push hooks not installed. "
            "Run `observal doctor patch --all --ide copilot` to inject them."
        )


def _check_copilot_cli(issues: list, warnings: list):
    """Check if Observal session push hooks are installed for Copilot CLI."""
    optic.debug("_check_copilot_cli")
    copilot_dir = Path.home() / ".copilot"
    if not copilot_dir.exists():
        rprint("  [dim]Copilot CLI not detected[/dim]")
        return

    hooks_path = copilot_dir / "hooks" / "observal.json"
    if not hooks_path.exists():
        warnings.append(
            "Copilot CLI session push hooks not installed. "
            "Run `observal doctor patch --all --ide copilot-cli` to inject them."
        )
        return

    data = _load_json(hooks_path)
    if data is None:
        issues.append(f"{hooks_path}: not valid JSON.")
        return

    hooks = data.get("hooks", {})
    has_session_push = False
    for event in ("sessionStart", "sessionEnd", "userPromptSubmitted"):
        entries = hooks.get(event, [])
        for e in entries:
            if "copilot_cli_session_push" in e.get("bash", ""):
                has_session_push = True
                break

    if not has_session_push:
        warnings.append(
            "Copilot CLI session push hooks not installed. "
            "Run `observal doctor patch --all --ide copilot-cli` to inject them."
        )


def _check_opencode(issues: list, warnings: list):
    """Check if Observal plugin is installed for OpenCode."""
    optic.debug("_check_opencode")
    opencode_dir = Path.home() / ".config" / "opencode"
    if not opencode_dir.exists():
        rprint("  [dim]OpenCode not detected[/dim]")
        return

    plugin_path = opencode_dir / "plugins" / "observal-plugin.ts"
    if not plugin_path.exists():
        warnings.append(
            "OpenCode observal plugin not installed. Run `observal doctor patch --all --ide opencode` to inject it."
        )


# ── Cleanup command ──────────────────────────────────────────


@doctor_app.command(name="cleanup")
def doctor_cleanup(
    ide: str = typer.Option(
        None,
        "--ide",
        "-i",
        help="Target IDE only (claude-code, kiro, cursor, codex, copilot, copilot-cli, opencode). Default: all.",
    ),
    exclude: list[str] = typer.Option(
        [],
        "--exclude",
        "-x",
        help="Exclude specific IDE(s) from cleanup (repeatable).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be removed without doing it"),
):
    """Remove ALL Observal hooks, env vars, and legacy telemetry config.

    Strips Observal-managed hooks and env vars from Claude Code and
    Kiro settings. Leaves non-Observal hooks untouched. Useful when you
    want to fully uninstall Observal instrumentation from an IDE without
    removing the IDE config files themselves.

    \b
    Examples:
      observal doctor cleanup                          # Clean all supported IDEs
      observal doctor cleanup --ide claude-code        # Claude Code only
      observal doctor cleanup --ide kiro               # Kiro only
      observal doctor cleanup --ide claude-code --dry-run  # Preview without changes
    """
    optic.trace("ide={}, exclude={}, dry_run={}", ide, exclude, dry_run)
    all_ides = ["claude-code", "kiro", "cursor", "codex", "copilot", "copilot-cli", "opencode"]
    targets = [ide] if ide else all_ides
    targets = [t for t in targets if t not in exclude]
    any_changes = False

    rprint("[bold]Observal Doctor - Cleanup[/bold]\n")

    for target in targets:
        if target in ("claude-code", "claude_code"):
            changed = _cleanup_claude_code(dry_run)
            any_changes = any_changes or changed

        elif target in ("kiro", "kiro-cli"):
            changed = _cleanup_kiro(dry_run)
            any_changes = any_changes or changed

        elif target == "cursor":
            changed = _cleanup_cursor(dry_run)
            any_changes = any_changes or changed

        elif target == "codex":
            changed = _cleanup_codex(dry_run)
            any_changes = any_changes or changed

        elif target == "copilot":
            changed = _cleanup_copilot(dry_run)
            any_changes = any_changes or changed

        elif target == "copilot-cli":
            changed = _cleanup_copilot_cli(dry_run)
            any_changes = any_changes or changed

        elif target == "opencode":
            changed = _cleanup_opencode(dry_run)
            any_changes = any_changes or changed

        else:
            rprint(f"[yellow]Unknown IDE: {target}[/yellow]")

    if any_changes and not dry_run:
        rprint("\n[green]✓ Cleanup complete.[/green] Restart your IDE sessions to take effect.")
    elif not any_changes:
        rprint("\n[dim]Nothing to clean up - no Observal artifacts found.[/dim]")


def _cleanup_claude_code(dry_run: bool) -> bool:
    optic.trace("dry_run={}", dry_run)
    rprint("[cyan]Claude Code[/cyan]")
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        rprint("  [dim]No settings.json found - skipping[/dim]")
        return False

    try:
        data = json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        rprint(f"  [red]Failed to read settings: {e}[/red]")
        return False

    changed = False

    # Remove Observal-managed env vars (OBSERVAL_*)
    env = data.get("env", {})
    removed_env = []
    for key in list(env):
        if key in MANAGED_ENV_KEYS:
            removed_env.append(key)
            if not dry_run:
                del env[key]
            changed = True
    if removed_env:
        verb = "Would remove" if dry_run else "Removed"
        rprint(f"  {verb} env vars: {', '.join(removed_env)}")

    # Remove Observal hooks from each event
    hooks = data.get("hooks", {})
    removed_events = []
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        cleaned = [g for g in groups if not _is_observal_matcher_group(g)]
        if len(cleaned) < len(groups):
            removed_events.append(f"{event} ({len(groups) - len(cleaned)} removed)")
            if not dry_run:
                if cleaned:
                    hooks[event] = cleaned
                else:
                    del hooks[event]
            changed = True
    if removed_events:
        verb = "Would remove" if dry_run else "Removed"
        rprint(f"  {verb} hooks: {', '.join(removed_events)}")

    if changed and not dry_run:
        # Clean up empty sections
        if not data.get("env"):
            data.pop("env", None)
        if not data.get("hooks"):
            data.pop("hooks", None)
        settings_path.write_text(json.dumps(data, indent=2) + "\n")
        rprint(f"  [green]Written {settings_path}[/green]")

    if not changed:
        rprint("  [dim]No Observal artifacts found[/dim]")

    return changed


def _cleanup_kiro(dry_run: bool) -> bool:
    optic.trace("dry_run={}", dry_run)
    rprint("[cyan]Kiro[/cyan]")
    agents_dir = Path.home() / ".kiro" / "agents"
    if not agents_dir.is_dir():
        rprint("  [dim]No ~/.kiro/agents/ found - skipping[/dim]")
        return False

    changed = False
    for agent_file in sorted(agents_dir.glob("*.json")):
        try:
            agent_data = json.loads(agent_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        agent_changed = False

        # Remove hooks that reference Observal
        hooks = agent_data.get("hooks", {})
        if isinstance(hooks, dict):
            for event, entries in list(hooks.items()):
                if not isinstance(entries, list):
                    continue
                cleaned = [e for e in entries if not _is_observal_hook_entry(e)]
                if len(cleaned) < len(entries):
                    agent_changed = True
                    if not dry_run:
                        if cleaned:
                            hooks[event] = cleaned
                        else:
                            del hooks[event]

        if agent_changed:
            changed = True
            verb = "Would clean" if dry_run else "Cleaned"
            rprint(f"  {verb} {agent_file.name}")
            if not dry_run:
                agent_file.write_text(json.dumps(agent_data, indent=2) + "\n")

    if not changed:
        rprint("  [dim]No Observal artifacts found in Kiro agents[/dim]")

    return changed


def _cleanup_cursor(dry_run: bool) -> bool:
    """Remove Observal hooks from ~/.cursor/hooks.json."""
    rprint("[cyan]Cursor[/cyan]")
    hooks_path = Path.home() / ".cursor" / "hooks.json"
    if not hooks_path.exists():
        rprint("  [dim]No ~/.cursor/hooks.json found - skipping[/dim]")
        return False

    try:
        data = json.loads(hooks_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        rprint(f"  [red]Failed to read hooks: {e}[/red]")
        return False

    hooks = data.get("hooks", {})
    changed = False
    removed_events = []

    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        cleaned = [
            h
            for h in entries
            if "cursor_session_push" not in h.get("command", "") and "session_push" not in h.get("command", "")
        ]
        if len(cleaned) < len(entries):
            removed_events.append(f"{event} ({len(entries) - len(cleaned)} removed)")
            if not dry_run:
                if cleaned:
                    hooks[event] = cleaned
                else:
                    del hooks[event]
            changed = True

    if changed:
        verb = "Would remove" if dry_run else "Removed"
        rprint(f"  {verb} hooks: {', '.join(removed_events)}")
        if not dry_run:
            if not data.get("hooks"):
                data.pop("hooks", None)
            hooks_path.write_text(json.dumps(data, indent=2) + "\n")
            rprint(f"  [green]Written {hooks_path}[/green]")
    else:
        rprint("  [dim]No Observal artifacts found[/dim]")

    return changed


def _cleanup_codex(dry_run: bool) -> bool:
    """Remove Observal hooks from ~/.codex/hooks.json."""
    rprint("[cyan]Codex[/cyan]")
    codex_dir = Path.home() / ".codex"
    hooks_path = codex_dir / "hooks.json"
    if not hooks_path.exists():
        rprint("  [dim]No ~/.codex/hooks.json found - skipping[/dim]")
        return False

    try:
        data = json.loads(hooks_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        rprint(f"  [red]Failed to read hooks: {e}[/red]")
        return False

    hooks = data.get("hooks", {})
    changed = False
    removed_events = []

    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        cleaned = [
            g
            for g in groups
            if not isinstance(g, dict)
            or not any("session_push" in h.get("command", "") for h in g.get("hooks", []) if isinstance(h, dict))
        ]
        if len(cleaned) < len(groups):
            removed_events.append(f"{event} ({len(groups) - len(cleaned)} removed)")
            if not dry_run:
                if cleaned:
                    hooks[event] = cleaned
                else:
                    del hooks[event]
            changed = True

    if changed:
        verb = "Would remove" if dry_run else "Removed"
        rprint(f"  {verb} hooks: {', '.join(removed_events)}")
        if not dry_run:
            if not data.get("hooks"):
                data.pop("hooks", None)
            hooks_path.write_text(json.dumps(data, indent=2) + "\n")
            rprint(f"  [green]Written {hooks_path}[/green]")
    else:
        rprint("  [dim]No Observal artifacts found[/dim]")

    return changed


def _cleanup_copilot(dry_run: bool) -> bool:
    """Remove Observal hooks from .github/hooks/observal.json and ~/.copilot/hooks/."""
    rprint("[cyan]Copilot (VS Code)[/cyan]")
    changed = False

    targets = [
        Path.cwd() / ".github" / "hooks" / "observal.json",
        Path.home() / ".copilot" / "hooks" / "observal.json",
    ]
    ps1_path = Path.cwd() / ".github" / "hooks" / "run_hook.ps1"

    for hooks_path in targets:
        if hooks_path.exists():
            verb = "Would remove" if dry_run else "Removed"
            rprint(f"  {verb} {hooks_path}")
            if not dry_run:
                hooks_path.unlink()
            changed = True

    if ps1_path.exists():
        existing = ps1_path.read_text()
        if "copilot_vscode_session_push" in existing:
            verb = "Would remove" if dry_run else "Removed"
            rprint(f"  {verb} {ps1_path}")
            if not dry_run:
                ps1_path.unlink()
            changed = True

    if not changed:
        rprint("  [dim]No Observal artifacts found[/dim]")

    return changed


def _cleanup_copilot_cli(dry_run: bool) -> bool:
    """Remove Observal hooks from ~/.copilot/hooks/observal.json."""
    rprint("[cyan]Copilot CLI[/cyan]")
    hooks_path = Path.home() / ".copilot" / "hooks" / "observal.json"

    if not hooks_path.exists():
        rprint("  [dim]No ~/.copilot/hooks/observal.json found - skipping[/dim]")
        return False

    verb = "Would remove" if dry_run else "Removed"
    rprint(f"  {verb} {hooks_path}")
    if not dry_run:
        hooks_path.unlink()

    return True


def _cleanup_opencode(dry_run: bool) -> bool:
    """Remove Observal plugin from ~/.config/opencode/plugins/."""
    rprint("[cyan]OpenCode[/cyan]")
    plugin_path = Path.home() / ".config" / "opencode" / "plugins" / "observal-plugin.ts"

    if not plugin_path.exists():
        rprint("  [dim]No observal plugin found - skipping[/dim]")
        return False

    verb = "Would remove" if dry_run else "Removed"
    rprint(f"  {verb} {plugin_path}")
    if not dry_run:
        plugin_path.unlink()

    return True


# ── Shim helpers ────────────────────────────────────────────


def _wrap_with_shim(entry: dict, mcp_id: str) -> dict:
    """Wrap an MCP server entry with observal-shim for telemetry."""
    optic.trace("entry={}, mcp_id={}", entry, mcp_id)
    if entry.get("url"):
        return entry
    shimmed = dict(entry)
    shimmed["command"] = "observal-shim"
    shimmed["args"] = ["--mcp-id", mcp_id, "--", entry.get("command", ""), *entry.get("args", [])]
    return shimmed


def _backup_config(config_path: Path) -> Path:
    """Create a timestamped backup of the config file."""
    optic.trace("config_path={}", config_path)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = config_path.with_suffix(f".pre-observal.{ts}.bak")
    shutil.copy2(config_path, backup)
    return backup


def _parse_mcp_servers(config_data: dict, ide: str) -> dict[str, dict]:
    """Extract MCP servers dict from IDE config using registry-defined key."""
    optic.trace("config_data={}, ide={}", config_data, ide)
    key = get_mcp_servers_key(ide)
    if key == "mcp.servers":
        return config_data.get("mcp", {}).get("servers", {})
    if key == "mcp":
        return config_data.get("mcp", {})
    if key == "servers":
        return config_data.get("servers", config_data.get("mcpServers", {}))
    if ide == "copilot-cli":
        return config_data.get("mcpServers", {})
    return config_data.get(key, config_data.get("servers", {}))


def _shim_config_file(config_path: Path, ide: str, dry_run: bool) -> int:
    """Wrap un-shimmed MCP servers in a config file with observal-shim.

    Returns count of newly shimmed entries.
    """
    optic.trace("config_path={}, ide={}", config_path, ide)
    if not config_path.exists():
        return 0
    try:
        data = json.loads(config_path.read_text())
    except Exception:
        return 0

    servers = _parse_mcp_servers(data, ide)
    shimmed = 0
    for name, entry in servers.items():
        if not _is_already_shimmed(entry) and not entry.get("url"):
            if not dry_run:
                servers[name] = _wrap_with_shim(entry, name)
            shimmed += 1

    if shimmed and not dry_run:
        _backup_config(config_path)
        config_path.write_text(json.dumps(data, indent=2) + "\n")

    return shimmed


_SHIM_TARGETS: dict[str, Path] = {ide: Path(path).expanduser() for ide, path in get_home_mcp_configs().items() if path}
_VALID_IDES = get_valid_ides()


# ── Patch command ────────────────────────────────────────────


@doctor_app.command(name="patch")
def doctor_patch(
    hook: bool = typer.Option(False, "--hook", help="Install session push hooks (Claude Code + Kiro)"),
    shim: bool = typer.Option(False, "--shim", help="Wrap MCP servers with observal-shim"),
    all_: bool = typer.Option(False, "--all", help="Hooks + shims"),
    all_ides: bool = typer.Option(False, "--all-ides", help="Target every detected IDE"),
    ide: list[str] = typer.Option([], "--ide", "-i", help="Target specific IDE (repeatable)"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would change without writing"),
):
    """Instrument IDEs with Observal telemetry hooks and shims.

    Requires at least one of --hook/--shim/--all AND one of --all-ides/--ide.
    Session JSONL hooks (--hook) are only supported for Claude Code and Kiro.
    MCP shim wrapping (--shim) works for all IDEs.

    \b
    Examples:
      observal doctor patch --all --all-ides           # Everything, everywhere
      observal doctor patch --hook --ide claude-code   # Claude Code hooks only
      observal doctor patch --shim --ide cursor        # Cursor shims only
      observal doctor patch --all --all-ides --dry-run # Preview changes
    """
    optic.trace("hook={}, shim={}", hook, shim)
    do_hooks = hook or all_
    do_shims = shim or all_

    if not (hook or shim or all_):
        rprint("[red]Specify at least one of --hook, --shim, or --all[/red]")
        raise typer.Exit(1)

    if not all_ides and not ide:
        rprint("[red]Specify --all-ides or --ide <name>[/red]")
        raise typer.Exit(1)

    cfg = config.load()
    server_url = cfg.get("server_url")
    if not server_url:
        rprint("[red]Not configured. Run [bold]observal auth login[/bold] first.[/red]")
        raise typer.Exit(1)

    targets = list(ide) if ide else _VALID_IDES if all_ides else []
    for t in targets:
        if t not in _VALID_IDES:
            rprint(f"[red]Unknown IDE: {t}. Valid: {', '.join(_VALID_IDES)}[/red]")
            raise typer.Exit(1)

    any_changes = False
    verb = "Would" if dry_run else "Done"
    rprint("[bold]Observal Doctor - Patch[/bold]\n")

    for target in targets:
        # ── Hooks ──
        if do_hooks:
            if target == "claude-code":
                changed = _patch_claude_code(dry_run)
                any_changes = any_changes or changed
            elif target == "kiro":
                changed = _patch_kiro(dry_run)
                any_changes = any_changes or changed
            elif target == "cursor":
                changed = _patch_cursor(dry_run)
                any_changes = any_changes or changed
            elif target == "pi":
                changed = _patch_pi(dry_run)
                any_changes = any_changes or changed
            elif target == "codex":
                changed = _patch_codex(dry_run)
            elif target == "copilot":
                changed = _patch_copilot(dry_run)
                any_changes = any_changes or changed
            elif target == "copilot-cli":
                changed = _patch_copilot_cli(dry_run)
                any_changes = any_changes or changed
            elif target == "opencode":
                changed = _patch_opencode(dry_run)
                any_changes = any_changes or changed

        # ── Shims (all IDEs with home MCP config) ──
        if do_shims:
            shim_path = _SHIM_TARGETS.get(target)
            if shim_path and shim_path.exists():
                rprint(f"[cyan]{target} - shims[/cyan]")
                count = _shim_config_file(shim_path, target, dry_run)
                if count:
                    any_changes = True
                    rprint(f"  {verb}: shimmed {count} MCP entries in {shim_path}")
                else:
                    rprint("  [dim]All MCP servers already shimmed[/dim]")

    if dry_run:
        rprint("\n[yellow]Dry run - no changes made.[/yellow]")
    elif any_changes:
        rprint("\n[green]✓ Patch complete.[/green] Restart your IDE sessions to pick up changes.")
        from observal_cli.audit import emit_cli_audit

        emit_cli_audit(
            "doctor.patch",
            resource_type="ide",
            detail=f"ides={','.join(targets)}, hooks={do_hooks}, shims={do_shims}",
            sensitivity="high",
        )
    else:
        rprint("\n[dim]Everything already up to date.[/dim]")


def _patch_claude_code(dry_run: bool) -> bool:
    """Install session push hooks into ~/.claude/settings.json."""
    optic.trace("dry_run={}", dry_run)
    from observal_cli import settings_reconciler

    rprint("[cyan]Claude Code - session push hooks[/cyan]")

    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        settings_path.parent.mkdir(parents=True, exist_ok=True)

    desired_hooks = get_desired_hooks()

    # No env vars needed for session push - config lives in ~/.observal/config.json
    changes = settings_reconciler.reconcile(desired_hooks, {}, dry_run=dry_run)

    if changes:
        for c in changes:
            rprint(f"  {c}")
        return True
    else:
        rprint("  [dim]Already up to date[/dim]")
        return False


def _patch_kiro(dry_run: bool) -> bool:
    """Install session push hooks into Kiro agent configs."""
    optic.trace("dry_run={}", dry_run)
    from observal_cli.ide_specs.kiro_hooks_spec import build_kiro_hooks

    rprint("[cyan]Kiro - session push hooks[/cyan]")

    agents_dir = Path.home() / ".kiro" / "agents"
    if not agents_dir.is_dir():
        rprint("  [dim]No ~/.kiro/agents/ directory - skipping[/dim]")
        return False

    agent_files = list(agents_dir.glob("*.json"))
    if not agent_files:
        rprint("  [dim]No agent configs found[/dim]")
        return False

    desired_hooks = build_kiro_hooks()
    changed = False

    for af in agent_files:
        agent_name = af.stem
        try:
            data = json.loads(af.read_text())
        except (json.JSONDecodeError, OSError):
            rprint(f"  [yellow]⚠ {agent_name}: could not parse, skipped[/yellow]")
            continue

        current_hooks = data.get("hooks", {})
        updated = False

        for event, desired_entries in desired_hooks.items():
            existing = current_hooks.get(event, [])
            # Remove old Observal hooks, keep non-Observal ones
            cleaned = [h for h in existing if not _is_observal_hook_entry(h)]
            new_list = cleaned + desired_entries
            if new_list != existing:
                current_hooks[event] = new_list
                updated = True

        if updated:
            data["hooks"] = current_hooks
            if not dry_run:
                af.write_text(json.dumps(data, indent=2) + "\n")
            verb = "Would update" if dry_run else "Updated"
            rprint(f"  {verb} {agent_name}")
            changed = True
        else:
            rprint(f"  [dim]{agent_name}: already up to date[/dim]")

    return changed


def _patch_cursor(dry_run: bool) -> bool:
    """Install session push hooks into ~/.cursor/hooks.json."""
    optic.trace("dry_run={}", dry_run)
    import sys

    rprint("[cyan]Cursor - session push hooks[/cyan]")

    hooks_path = Path.home() / ".cursor" / "hooks.json"
    if not hooks_path.parent.is_dir():
        rprint("  [dim]No ~/.cursor/ directory - skipping[/dim]")
        return False

    # Use the current interpreter (from the observal CLI's venv) so that
    # httpx and other dependencies are available when Cursor fires the hook.
    cmd = f"{sys.executable} -m observal_cli.hooks.cursor_session_push"

    desired = {
        "version": 1,
        "hooks": {
            "beforeSubmitPrompt": [{"command": cmd, "type": "command"}],
            "stop": [{"command": cmd, "type": "command"}],
        },
    }

    # Load existing hooks.json if present
    existing = {}
    if hooks_path.exists():
        try:
            existing = json.loads(hooks_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Check if already patched
    existing_hooks = existing.get("hooks", {})
    needs_update = False

    for event in ("beforeSubmitPrompt", "stop"):
        entries = existing_hooks.get(event, [])
        has_observal = any("cursor_session_push" in e.get("command", "") for e in entries)
        if not has_observal:
            needs_update = True
            break

    if not needs_update:
        rprint("  [dim]Already up to date[/dim]")
        return False

    # Merge: keep existing non-Observal hooks, add ours
    merged_hooks = existing_hooks.copy()
    for event, desired_entries in desired["hooks"].items():
        current = merged_hooks.get(event, [])
        # Remove old Observal hooks
        cleaned = [
            h
            for h in current
            if "cursor_session_push" not in h.get("command", "") and "session_push" not in h.get("command", "")
        ]
        merged_hooks[event] = cleaned + desired_entries

    result = {"version": 1, "hooks": merged_hooks}

    if not dry_run:
        hooks_path.write_text(json.dumps(result, indent=2) + "\n")

    verb = "Would install" if dry_run else "Installed"
    rprint(f"  {verb} hooks in {hooks_path}")
    return True


def _patch_pi(dry_run: bool) -> bool:
    """Install observal-pi into ~/.pi/agent/settings.json packages."""
    optic.trace("dry_run={}", dry_run)

    rprint("[cyan]Pi - session telemetry extension[/cyan]")

    pi_dir = Path.home() / ".pi" / "agent"
    if not pi_dir.is_dir():
        rprint("  [dim]No ~/.pi/agent/ directory - skipping[/dim]")
        return False

    settings_path = pi_dir / "settings.json"
    package_spec = "npm:observal-pi"

    # Load existing settings
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}

    packages = data.get("packages", [])

    # Check if already installed
    already_installed = any(package_spec in (p if isinstance(p, str) else p.get("source", "")) for p in packages)

    if already_installed:
        rprint("  [dim]Already installed[/dim]")
        return False

    # Add the package
    packages.append(package_spec)
    data["packages"] = packages

    if not dry_run:
        if settings_path.exists():
            _backup_config(settings_path)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(data, indent=2) + "\n")

    verb = "Would install" if dry_run else "Installed"
    rprint(f"  {verb} {package_spec} in {settings_path}")
    rprint("  [dim]Restart pi or run /reload to activate[/dim]")
    return True


def _patch_codex(dry_run: bool) -> bool:
    """Install session push hooks into ~/.codex/hooks.json and enable codex_hooks flag."""
    optic.debug("_patch_codex: dry_run={}", dry_run)
    from observal_cli.ide_specs.codex_hooks_spec import build_codex_hooks

    rprint("[cyan]Codex - session push hooks[/cyan]")

    codex_dir = Path.home() / ".codex"
    hooks_path = codex_dir / "hooks.json"
    config_path = codex_dir / "config.toml"

    desired = build_codex_hooks()

    # Load existing hooks.json if present
    existing: dict = {}
    if hooks_path.exists():
        try:
            existing = json.loads(hooks_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Check if already patched
    existing_hooks = existing.get("hooks", {})
    needs_update = False

    for event in ("UserPromptSubmit", "Stop"):
        groups = existing_hooks.get(event, [])
        has_observal = any(
            "codex_session_push" in h.get("command", "")
            for g in groups
            if isinstance(g, dict)
            for h in g.get("hooks", [])
            if isinstance(h, dict)
        )
        if not has_observal:
            needs_update = True
            break

    # Also check if codex_hooks flag needs enabling
    needs_flag = False
    if config_path.exists():
        try:
            content = config_path.read_text()
            if "codex_hooks" not in content or "codex_hooks = false" in content:
                needs_flag = True
        except OSError:
            needs_flag = True
    else:
        needs_flag = True

    if not needs_update and not needs_flag:
        rprint("  [dim]Already up to date[/dim]")
        return False

    # Merge hooks: preserve non-Observal hooks, add ours
    if needs_update:
        merged_hooks = existing_hooks.copy()
        for event, desired_groups in desired["hooks"].items():
            current = merged_hooks.get(event, [])
            # Remove old Observal hook groups
            cleaned = [
                g
                for g in current
                if not isinstance(g, dict)
                or not any("session_push" in h.get("command", "") for h in g.get("hooks", []) if isinstance(h, dict))
            ]
            merged_hooks[event] = cleaned + desired_groups

        result = {"hooks": merged_hooks}

        if not dry_run:
            codex_dir.mkdir(parents=True, exist_ok=True)
            hooks_path.write_text(json.dumps(result, indent=2) + "\n")

        verb = "Would install" if dry_run else "Installed"
        rprint(f"  {verb} hooks in {hooks_path}")

    # Enable codex_hooks flag in config.toml
    if needs_flag:
        if not dry_run:
            codex_dir.mkdir(parents=True, exist_ok=True)
            if config_path.exists():
                content = config_path.read_text()
                if "codex_hooks = false" in content:
                    content = content.replace("codex_hooks = false", "codex_hooks = true")
                elif "codex_hooks" not in content:
                    content = f"codex_hooks = true\n{content}"
                config_path.write_text(content)
            else:
                config_path.write_text("codex_hooks = true\n")

        verb = "Would enable" if dry_run else "Enabled"
        rprint(f"  {verb} codex_hooks flag in {config_path}")

    return True


def _patch_copilot(dry_run: bool) -> bool:
    """Install session push hooks for Copilot (VS Code).

    1. Installs hooks at .github/hooks/observal.json (project-level)
    2. Installs run_hook.ps1 wrapper script
    """
    optic.debug("_patch_copilot: dry_run={}", dry_run)
    from observal_cli.ide_specs.copilot_hooks_spec import build_copilot_hooks, build_copilot_run_hook_ps1

    rprint("[cyan]Copilot (VS Code) - session push hooks[/cyan]")

    any_changes = False

    # ── Part 1: Install hooks at .github/hooks/observal.json ──
    hooks_dir = Path.cwd() / ".github" / "hooks"
    hooks_path = hooks_dir / "observal.json"

    desired = build_copilot_hooks()

    existing: dict = {}
    if hooks_path.exists():
        try:
            existing = json.loads(hooks_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    existing_hooks = existing.get("hooks", {})
    needs_hook_update = False

    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        entries = existing_hooks.get(event, [])
        has_observal = any(
            "run_hook.ps1" in e.get("command", "") or "copilot_cli_session_push" in e.get("command", e.get("bash", ""))
            for e in entries
        )
        if not has_observal:
            needs_hook_update = True
            break

    if needs_hook_update:
        merged_hooks = existing_hooks.copy()
        for event, desired_entries in desired["hooks"].items():
            current = merged_hooks.get(event, [])
            cleaned = [
                h
                for h in current
                if "run_hook.ps1" not in h.get("command", "")
                and "copilot_cli_session_push" not in h.get("command", h.get("bash", ""))
                and "session_push" not in h.get("command", h.get("bash", ""))
            ]
            merged_hooks[event] = cleaned + desired_entries

        result = {"version": 1, "hooks": merged_hooks}

        if not dry_run:
            hooks_dir.mkdir(parents=True, exist_ok=True)
            hooks_path.write_text(json.dumps(result, indent=2) + "\n")

        verb = "Would install" if dry_run else "Installed"
        rprint(f"  {verb} hooks in {hooks_path}")
        any_changes = True
    else:
        rprint("  [dim]Hooks already up to date[/dim]")

    # ── Part 1b: Install run_hook.ps1 wrapper ──
    ps1_path = hooks_dir / "run_hook.ps1"
    # Resolve the Windows Python path for the PS1 wrapper.
    # On Windows: sys.executable is already correct.
    # On WSL/Linux: the PS1 runs on Windows, so we need the Windows-side
    # uv tools Python path. Detect WSL and resolve accordingly.
    import sys as _sys

    if _sys.platform == "win32":
        python_path = _sys.executable
    else:
        # Running from WSL/Linux: resolve Windows uv tools path
        # Standard location: %APPDATA%/uv/tools/observal-cli/Scripts/python.exe
        # In WSL this maps to /mnt/c/Users/<user>/AppData/Roaming/uv/tools/...
        import os

        # Try to find the Windows user profile via environment or /mnt/c/Users
        win_appdata = os.environ.get("APPDATA_WIN", "")
        if not win_appdata:
            # Infer from WSL mount: find the Windows username
            # Check if running under /mnt/c/Users/<name>/...
            cwd_str = str(Path.cwd())
            if "/mnt/c/Users/" in cwd_str:
                win_user = cwd_str.split("/mnt/c/Users/")[1].split("/")[0]
                python_path = f"C:\\Users\\{win_user}\\AppData\\Roaming\\uv\\tools\\observal-cli\\Scripts\\python.exe"
            else:
                # Fallback: use bare 'python' and hope it's on Windows PATH
                python_path = "python"
        else:
            python_path = f"{win_appdata}\\uv\\tools\\observal-cli\\Scripts\\python.exe"

    script_path = "observal_cli\\hooks\\copilot_vscode_session_push.py"
    ps1_content = build_copilot_run_hook_ps1(python_path, script_path)

    needs_ps1_update = True
    if ps1_path.exists():
        existing_ps1 = ps1_path.read_text()
        if "copilot_vscode_session_push" in existing_ps1:
            needs_ps1_update = False

    if needs_ps1_update:
        if not dry_run:
            hooks_dir.mkdir(parents=True, exist_ok=True)
            ps1_path.write_text(ps1_content)
        verb = "Would install" if dry_run else "Installed"
        rprint(f"  {verb} PowerShell wrapper at {ps1_path}")
        any_changes = True

    return any_changes


def _patch_copilot_cli(dry_run: bool) -> bool:
    """Install session push hooks into ~/.copilot/hooks/observal.json."""
    optic.debug("_patch_copilot_cli: dry_run={}", dry_run)
    from observal_cli.ide_specs.copilot_cli_hooks_spec import build_copilot_cli_hooks

    rprint("[cyan]Copilot CLI - session push hooks[/cyan]")

    hooks_dir = Path.home() / ".copilot" / "hooks"
    hooks_path = hooks_dir / "observal.json"

    desired = build_copilot_cli_hooks()

    # Load existing hook file if present
    existing: dict = {}
    if hooks_path.exists():
        try:
            existing = json.loads(hooks_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Check if already patched
    existing_hooks = existing.get("hooks", {})
    needs_update = False

    for event in ("sessionStart", "sessionEnd", "userPromptSubmitted", "preToolUse", "postToolUse"):
        entries = existing_hooks.get(event, [])
        has_observal = any("copilot_cli_session_push" in e.get("bash", "") for e in entries)
        if not has_observal:
            needs_update = True
            break

    if not needs_update:
        rprint("  [dim]Already up to date[/dim]")
        return False

    # Merge: keep existing non-Observal hooks, add ours
    merged_hooks = existing_hooks.copy()
    for event, desired_entries in desired["hooks"].items():
        current = merged_hooks.get(event, [])
        # Remove old Observal hooks
        cleaned = [
            h
            for h in current
            if "copilot_cli_session_push" not in h.get("bash", "") and "session_push" not in h.get("bash", "")
        ]
        merged_hooks[event] = cleaned + desired_entries

    result = {"version": 1, "hooks": merged_hooks}

    if not dry_run:
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text(json.dumps(result, indent=2) + "\n")

    verb = "Would install" if dry_run else "Installed"
    rprint(f"  {verb} hooks in {hooks_path}")
    return True


def _patch_opencode(dry_run: bool) -> bool:
    """Install observal telemetry plugin into ~/.config/opencode/plugins/."""
    optic.debug("_patch_opencode: dry_run={}", dry_run)
    from observal_cli.ide_specs.opencode_hooks_spec import get_plugin_source

    rprint("[cyan]OpenCode - telemetry plugin[/cyan]")

    plugins_dir = Path.home() / ".config" / "opencode" / "plugins"
    plugin_path = plugins_dir / "observal-plugin.ts"

    # Check if already installed
    if plugin_path.exists():
        existing = plugin_path.read_text()
        if "observal" in existing.lower() and "offline stub" not in existing:
            rprint("  [dim]Already installed[/dim]")
            return False

    plugin_source = get_plugin_source()

    if not dry_run:
        plugins_dir.mkdir(parents=True, exist_ok=True)
        plugin_path.write_text(plugin_source)

    verb = "Would install" if dry_run else "Installed"
    rprint(f"  {verb} plugin at {plugin_path}")
    return True
