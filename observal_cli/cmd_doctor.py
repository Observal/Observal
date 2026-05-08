"""observal doctor: diagnose and patch IDE settings for Observal session telemetry.

Supports Claude Code and Kiro.  Injects 2 hooks (UserPromptSubmit + Stop) that
push session JSONL incrementally to the server.
"""

import json
from pathlib import Path

import typer
from rich import print as rprint

from observal_cli import config
from observal_cli.ide_specs.claude_code_hooks_spec import (
    MANAGED_ENV_KEYS,
    OBSERVAL_METADATA_KEY,
    get_desired_hooks,
    is_observal_matcher_group,
)

doctor_app = typer.Typer(help="Diagnose and patch IDE settings for Observal telemetry")


# ── Markers that identify old Observal-injected content ──────

_LEGACY_HOOK_MARKERS = (
    "observal-hook",
    "observal-stop-hook",
    "observal_cli.hooks.kiro_hook",
    "observal_cli.hooks.kiro_stop_hook",
    "observal_cli.hooks.gemini_hook",
    "observal_cli.hooks.gemini_stop_hook",
    "observal_cli.hooks.copilot_cli_hook",
    "observal_cli.hooks.copilot_cli_stop_hook",
    "observal_cli.hooks.buffer_event",
    "observal_cli.hooks.flush_buffer",
    "observal_cli.hooks.session_push",
    "observal_cli.hooks.kiro_session_push",
    "/api/v1/telemetry/hooks",
    "/api/v1/otel/hooks",
)


def _is_observal_hook_entry(entry: dict) -> bool:
    cmd = entry.get("command", "")
    url = entry.get("url", "")
    return any(m in cmd or m in url for m in _LEGACY_HOOK_MARKERS)


def _is_observal_matcher_group(group: dict) -> bool:
    if OBSERVAL_METADATA_KEY in group:
        return True
    return any(_is_observal_hook_entry(h) for h in group.get("hooks", []))


# ── Helpers ──────────────────────────────────────────────────


def _load_json(path: Path) -> dict | None:
    try:
        text = path.read_text()
        stripped = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))
        return json.loads(stripped)
    except Exception:
        return None


# ── Diagnose command ─────────────────────────────────────────


@doctor_app.callback(invoke_without_command=True)
def doctor(ctx: typer.Context):
    """Diagnose IDE and Observal settings for compatibility issues."""
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

    raise typer.Exit(1 if issues else 0)


def _check_observal_config(issues: list, warnings: list):
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
            "Run `observal doctor patch --ide claude-code` to inject them."
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

    # Check for stale OTEL env vars
    env = data.get("env", {})
    stale_otel = [k for k in env if k.startswith("OTEL_")]
    if stale_otel:
        warnings.append(
            f"Stale OTEL env vars in settings.json: {', '.join(stale_otel)}. "
            "Run `observal doctor cleanup --ide claude-code` to remove them."
        )


def _check_kiro(issues: list, warnings: list):
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
            "Run `observal doctor patch --ide kiro` to inject them."
        )


# ── Cleanup command ──────────────────────────────────────────


@doctor_app.command(name="cleanup")
def doctor_cleanup(
    ide: str = typer.Option(
        None,
        "--ide",
        "-i",
        help="Target IDE only (claude-code, kiro). Default: all.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be removed without doing it"),
):
    """Remove ALL Observal hooks, env vars, and legacy telemetry config.

    Strips Observal-managed hooks and OTEL env vars from Claude Code and
    Kiro settings. Leaves non-Observal hooks untouched.
    """
    targets = [ide] if ide else ["claude-code", "kiro"]
    any_changes = False

    rprint("[bold]Observal Doctor — Cleanup[/bold]\n")

    for target in targets:
        if target in ("claude-code", "claude_code"):
            changed = _cleanup_claude_code(dry_run)
            any_changes = any_changes or changed

        elif target in ("kiro", "kiro-cli"):
            changed = _cleanup_kiro(dry_run)
            any_changes = any_changes or changed

        else:
            rprint(f"[yellow]Unknown IDE: {target}[/yellow]")

    if any_changes and not dry_run:
        rprint("\n[green]✓ Cleanup complete.[/green] Restart your IDE sessions to take effect.")
    elif not any_changes:
        rprint("\n[dim]Nothing to clean up — no Observal artifacts found.[/dim]")


def _cleanup_claude_code(dry_run: bool) -> bool:
    rprint("[cyan]Claude Code[/cyan]")
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        rprint("  [dim]No settings.json found — skipping[/dim]")
        return False

    try:
        data = json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        rprint(f"  [red]Failed to read settings: {e}[/red]")
        return False

    changed = False

    # Remove Observal-managed env vars (OTEL_*, OBSERVAL_*)
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
    rprint("[cyan]Kiro[/cyan]")
    agents_dir = Path.home() / ".kiro" / "agents"
    if not agents_dir.is_dir():
        rprint("  [dim]No ~/.kiro/agents/ found — skipping[/dim]")
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


# ── Patch command ────────────────────────────────────────────


@doctor_app.command(name="patch")
def doctor_patch(
    ide: list[str] = typer.Option([], "--ide", "-i", help="Target IDE (claude-code, kiro). Repeatable."),
    all_ides: bool = typer.Option(False, "--all-ides", help="Target all supported IDEs"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would change without writing"),
):
    """Install Observal session push hooks into IDE settings.

    Injects 2 hooks (UserPromptSubmit + Stop) that push session JSONL
    data incrementally to the Observal server.

    \b
    Examples:
      observal doctor patch --all-ides            # Claude Code + Kiro
      observal doctor patch --ide claude-code     # Claude Code only
      observal doctor patch --ide kiro            # Kiro only
      observal doctor patch --all-ides --dry-run  # Preview changes
    """
    if not all_ides and not ide:
        rprint("[red]Specify --all-ides or --ide <name>[/red]")
        raise typer.Exit(1)

    valid_ides = ("claude-code", "kiro")
    targets = list(ide) if ide else list(valid_ides)
    for t in targets:
        if t not in valid_ides:
            rprint(f"[red]Unknown IDE: {t}. Valid: {', '.join(valid_ides)}[/red]")
            raise typer.Exit(1)

    cfg = config.load()
    server_url = cfg.get("server_url")
    if not server_url:
        rprint("[red]Not configured. Run [bold]observal auth login[/bold] first.[/red]")
        raise typer.Exit(1)

    any_changes = False
    rprint("[bold]Observal Doctor — Patch[/bold]\n")

    for target in targets:
        if target == "claude-code":
            changed = _patch_claude_code(dry_run)
            any_changes = any_changes or changed

        elif target == "kiro":
            changed = _patch_kiro(dry_run)
            any_changes = any_changes or changed

    if dry_run:
        rprint("\n[yellow]Dry run — no changes made.[/yellow]")
    elif any_changes:
        rprint("\n[green]✓ Patch complete.[/green] Restart your IDE sessions to pick up changes.")
    else:
        rprint("\n[dim]Everything already up to date.[/dim]")


def _patch_claude_code(dry_run: bool) -> bool:
    """Install session push hooks into ~/.claude/settings.json."""
    from observal_cli import settings_reconciler

    rprint("[cyan]Claude Code — session push hooks[/cyan]")

    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        settings_path.parent.mkdir(parents=True, exist_ok=True)

    desired_hooks = get_desired_hooks()

    # No env vars needed for session push — config lives in ~/.observal/config.json
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
    from observal_cli.ide_specs.kiro_hooks_spec import build_kiro_hooks

    rprint("[cyan]Kiro — session push hooks[/cyan]")

    agents_dir = Path.home() / ".kiro" / "agents"
    if not agents_dir.is_dir():
        rprint("  [dim]No ~/.kiro/agents/ directory — skipping[/dim]")
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
