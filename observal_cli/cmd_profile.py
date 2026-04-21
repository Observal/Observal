"""observal use: swap IDE configs from git-hosted profiles."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich import print as rprint

BACKUP_DIR = Path.home() / ".observal" / "backups"
PROFILES_DIR = Path.home() / ".observal" / "profiles"
STATE_FILE = Path.home() / ".observal" / "profile_state.json"

# IDE config paths: what files a profile can provide and where they go
IDE_FILE_MAP = {
    # Claude Code
    ".claude/settings.json": Path.home() / ".claude" / "settings.json",
    ".claude/settings.local.json": Path.home() / ".claude" / "settings.local.json",
    ".mcp.json": None,  # project-level, resolved at use time
    ".claude/agents/": Path.home() / ".claude" / "agents",
    "CLAUDE.md": None,  # project-level
    # Kiro
    ".kiro/settings.json": Path.home() / ".kiro" / "settings.json",
    ".kiro/settings/cli.json": Path.home() / ".kiro" / "settings" / "cli.json",
    ".kiro/agents/": Path.home() / ".kiro" / "agents",
    ".kiro/hooks/": Path.home() / ".kiro" / "hooks",
    ".kiro/skills/": Path.home() / ".kiro" / "skills",
    # Cursor
    ".cursor/mcp.json": Path.home() / ".cursor" / "mcp.json",
    ".cursor/rules": None,  # project-level
    ".cursorrules": None,  # project-level
    # Gemini CLI
    ".gemini/settings.json": Path.home() / ".gemini" / "settings.json",
    ".gemini/GEMINI.md": Path.home() / ".gemini" / "GEMINI.md",
    # GitHub Copilot (VS Code)
    ".vscode/mcp.json": Path.home() / ".vscode" / "mcp.json",
    ".github/copilot-instructions.md": None,  # project-level
    # OpenCode
    ".config/opencode/opencode.json": Path.home() / ".config" / "opencode" / "opencode.json",
    # Codex
    ".codex/config.toml": Path.home() / ".codex" / "config.toml",
    "AGENTS.md": None,  # project-level
}

# Files that are project-level (placed in CWD, not home)
PROJECT_FILES = {
    ".mcp.json",
    ".cursor/rules",
    ".cursorrules",
    "CLAUDE.md",
    ".github/copilot-instructions.md",
    "AGENTS.md",
}


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _backup_current(label: str) -> Path:
    """Back up all existing IDE config files into a timestamped directory."""
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"{label}_{ts}"
    backup_path.mkdir(parents=True, exist_ok=True)

    backed_up = []
    for rel_path, dest in IDE_FILE_MAP.items():
        target = dest if dest else Path.cwd() / rel_path
        if target.exists():
            backup_dest = backup_path / rel_path
            backup_dest.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                shutil.copytree(target, backup_dest, dirs_exist_ok=True)
            else:
                shutil.copy2(target, backup_dest)
            backed_up.append(rel_path)

    if backed_up:
        (backup_path / "manifest.json").write_text(
            json.dumps(
                {
                    "label": label,
                    "timestamp": ts,
                    "files": backed_up,
                },
                indent=2,
            )
        )

    return backup_path


def _clone_profile(source: str, ref: str | None = None) -> Path:
    """Clone or update a profile repo."""
    # Derive a name from the source
    name = source.rstrip("/").split("/")[-1].removesuffix(".git")
    profile_path = PROFILES_DIR / name

    if profile_path.exists():
        # Pull latest
        rprint(f"  [dim]Updating {name}...[/dim]")
        subprocess.run(["git", "pull", "--ff-only"], cwd=profile_path, capture_output=True)
    else:
        rprint(f"  [dim]Cloning {source}...[/dim]")
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", "--depth", "1"]
        if ref:
            cmd += ["--branch", ref]
        cmd += [source, str(profile_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            rprint(f"[red]Failed to clone: {result.stderr.strip()}[/red]")
            raise typer.Exit(1)

    if ref and profile_path.exists():
        subprocess.run(["git", "checkout", ref], cwd=profile_path, capture_output=True)

    return profile_path


def _apply_profile(profile_path: Path) -> list[str]:
    """Copy profile files to their IDE destinations. Returns list of applied files."""
    applied = []

    for rel_path, dest in IDE_FILE_MAP.items():
        source = profile_path / rel_path
        if not source.exists():
            continue

        target = dest if dest else Path.cwd() / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)

        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        applied.append(rel_path)

    return applied


def _restore_backup(backup_path: Path) -> list[str]:
    """Restore files from a backup directory."""
    manifest_file = backup_path / "manifest.json"
    if not manifest_file.exists():
        return []

    manifest = json.loads(manifest_file.read_text())
    restored = []

    for rel_path in manifest.get("files", []):
        source = backup_path / rel_path
        dest = IDE_FILE_MAP.get(rel_path)
        target = dest if dest else Path.cwd() / rel_path

        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            restored.append(rel_path)

    return restored


def register_use(app: typer.Typer):
    @app.command("use")
    def use_profile(
        profile: str = typer.Argument(help="Git URL, local path, or 'default' to restore backup"),
        ref: str = typer.Option(None, "--ref", "-r", help="Git branch/tag/commit to checkout"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ):
        """Swap your IDE configs to a profile. Backs up current config first.

        Examples:
            observal use https://github.com/user/my-profile
            observal use https://github.com/user/my-profile --ref v2.0
            observal use ./local-profile
            observal use default
        """
        state = _load_state()

        # Restore default (previous backup)
        if profile == "default":
            last_backup = state.get("last_backup")
            if not last_backup or not Path(last_backup).exists():
                rprint("[yellow]No backup found. Nothing to restore.[/yellow]")
                raise typer.Exit(1)

            rprint(f"[cyan]Restoring from backup: {last_backup}[/cyan]")
            restored = _restore_backup(Path(last_backup))
            if restored:
                for f in restored:
                    rprint(f"  [green]restored[/green] {f}")
                state["active_profile"] = None
                state["active_profile_name"] = None
                _save_state(state)
                rprint(f"\n[bold green]Restored {len(restored)} file(s) from backup.[/bold green]")
            else:
                rprint("[yellow]Backup was empty, nothing to restore.[/yellow]")
            return

        # Resolve profile source
        profile_path: Path
        if profile.startswith("http") or profile.startswith("git@"):
            rprint(f"[cyan]Fetching profile from {profile}...[/cyan]")
            profile_path = _clone_profile(profile, ref)
        elif Path(profile).exists():
            profile_path = Path(profile).resolve()
        else:
            # Check if it's a cached profile name
            cached = PROFILES_DIR / profile
            if cached.exists():
                profile_path = cached
                if ref:
                    subprocess.run(["git", "checkout", ref], cwd=profile_path, capture_output=True)
            else:
                rprint(f"[red]Profile not found: {profile}[/red]")
                rprint("[dim]Provide a git URL, local path, or cached profile name.[/dim]")
                raise typer.Exit(1)

        # Check what the profile contains
        profile_files = []
        for rel_path in IDE_FILE_MAP:
            if (profile_path / rel_path).exists():
                profile_files.append(rel_path)

        if not profile_files:
            rprint("[yellow]Profile contains no recognized IDE config files.[/yellow]")
            rprint("[dim]Expected files like .claude/settings.json, .kiro/settings.json, .mcp.json, etc.[/dim]")
            raise typer.Exit(1)

        # Show what will happen
        rprint(f"\n[bold]Profile: {profile_path.name}[/bold]")

        # Read profile README if it exists
        readme = profile_path / "README.md"
        if readme.exists():
            desc = readme.read_text().split("\n")[0].lstrip("# ").strip()
            if desc:
                rprint(f"[dim]{desc}[/dim]")

        rprint(f"\nWill install {len(profile_files)} config file(s):")
        for f in profile_files:
            dest = IDE_FILE_MAP.get(f)
            target = dest if dest else Path.cwd() / f
            exists = "[yellow]overwrite[/yellow]" if target.exists() else "[green]new[/green]"
            rprint(f"  {exists} {f}")

        if not yes:
            confirm = typer.confirm("\nProceed? Current configs will be backed up first")
            if not confirm:
                raise typer.Abort()

        # Backup current
        rprint("\n[cyan]Backing up current configs...[/cyan]")
        backup_path = _backup_current("pre_profile")
        rprint(f"  [dim]Backup saved to {backup_path}[/dim]")

        # Apply profile
        rprint("[cyan]Applying profile...[/cyan]")
        applied = _apply_profile(profile_path)
        for f in applied:
            rprint(f"  [green]applied[/green] {f}")

        # Save state
        state["active_profile"] = str(profile_path)
        state["active_profile_name"] = profile_path.name
        state["last_backup"] = str(backup_path)
        state["applied_at"] = datetime.now(UTC).isoformat()
        _save_state(state)

        rprint(f"\n[bold green]Profile '{profile_path.name}' applied. {len(applied)} file(s) installed.[/bold green]")
        rprint("[dim]Run `observal use default` to restore your previous config.[/dim]")

    @app.command("profile")
    def profile_status():
        """Show active profile and backup info."""
        state = _load_state()
        active = state.get("active_profile_name")
        if active:
            rprint(f"[bold]Active profile:[/bold] {active}")
            rprint(f"[dim]Source: {state.get('active_profile')}[/dim]")
            rprint(f"[dim]Applied: {state.get('applied_at', 'unknown')}[/dim]")
            rprint(f"[dim]Backup: {state.get('last_backup')}[/dim]")
        else:
            rprint("[dim]No profile active. Using default IDE configs.[/dim]")

        # List cached profiles
        if PROFILES_DIR.exists():
            cached = [d.name for d in PROFILES_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")]
            if cached:
                rprint(f"\n[bold]Cached profiles:[/bold] {', '.join(cached)}")

        # List backups
        if BACKUP_DIR.exists():
            backups = sorted(BACKUP_DIR.iterdir(), reverse=True)
            if backups:
                rprint(f"\n[bold]Backups:[/bold] {len(backups)}")
                for b in backups[:5]:
                    manifest = b / "manifest.json"
                    if manifest.exists():
                        m = json.loads(manifest.read_text())
                        rprint(f"  [dim]{b.name}: {len(m.get('files', []))} files[/dim]")
