# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Skill registry CLI commands."""

from __future__ import annotations

import json as _json
import re
import subprocess
import tempfile
from pathlib import Path

import typer
from loguru import logger
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.constants import VALID_SKILL_TASK_TYPES
from observal_cli.prompts import select_one, text_input
from observal_cli.render import console, kv_panel, output_json, relative_time, spinner, status_badge
from observal_cli.shared.utils import sanitize_name as _sanitize_name

skill_app = typer.Typer(help="Skill registry commands")


def register_skill(app: typer.Typer):
    logger.debug("register_skill called")
    app.add_typer(skill_app, name="skill")


# ── Security helpers (port of vercel-labs installer.ts) ─────────────────────


def _is_path_safe(path: Path, base: Path) -> bool:
    """Return True only if resolved *path* is inside *base* (no traversal)."""
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


# ── Frontmatter parser (mirrors vercel-labs parseFrontmatter) ───────────────

_FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---", re.DOTALL)


def _parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from markdown.  Uses yaml.safe_load (no eval)."""
    try:
        import yaml  # only needed locally; server-side already does this
    except ImportError:
        return {}
    m = _FM_RE.match(content)
    if not m:
        return {}
    try:
        result = yaml.safe_load(m.group(1))
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


# ── Submit ────────────────────────────────────────────────────────────────────


@skill_app.command(name="submit")
def skill_submit(
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Create from JSON file"),
    skill_md: str | None = typer.Option(None, "--skill-md", help="Path to SKILL.md to paste (auto-fills fields)"),
    git_url: str | None = typer.Option(None, "--git-url", help="Git repository URL"),
    git_ref: str | None = typer.Option(None, "--git-ref", help="Branch or tag (default: main)"),
    script: str | None = typer.Option(None, "--script", help="Path to script file (registry_direct mode)"),
    delivery_mode: str | None = typer.Option(None, "--delivery-mode", help="Delivery: git_fetch or registry_direct"),
    draft: bool = typer.Option(False, "--draft", help="Save as draft instead of submitting for review"),
    submit_draft: str | None = typer.Option(None, "--submit", help="Submit a draft for review (skill ID)"),
):
    """Submit a new skill for review.

    Skills are reusable SKILL.md files that provide agents with task-specific
    instructions. Preferred: provide --git-url (with optional --git-ref) and
    let the server fetch SKILL.md automatically.

    Shortcut: provide --skill-md PATH to paste the SKILL.md content directly
    (fields are auto-filled from frontmatter; --git-url is still required
    for install unless using --delivery-mode registry_direct).

    Registry direct: use --delivery-mode registry_direct with --skill-md and
    optionally --script to submit a skill with inline content (no git repo
    needed). On install, the SKILL.md and script are written directly.

    Only submit skills you created or are the point-of-contact for.

    Examples:
        observal registry skill submit --git-url https://github.com/org/repo
        observal registry skill submit --from-file skill.json
        observal registry skill submit --skill-md ./SKILL.md --git-url https://github.com/org/repo
        observal registry skill submit --skill-md ./SKILL.md --script ./run.sh --delivery-mode registry_direct
        observal registry skill submit --draft
        observal registry skill submit --submit abc123
    """
    rprint("[dim]Note: Only submit components you created (private) or are the point-of-contact for (external).[/dim]")
    if draft and submit_draft:
        rprint(
            "[red]Cannot use --draft and --submit together.[/red] "
            "Use --draft to save a new draft, or --submit to submit an existing draft."
        )
        raise typer.Exit(code=1)

    if submit_draft:
        resolved = config.resolve_alias(submit_draft)
        with spinner("Submitting draft for review..."):
            result = client.post(f"/api/v1/skills/{resolved}/submit")
        rprint(f"[green]✓ Draft submitted for review![/green] ID: [bold]{result['id']}[/bold]")
        return

    if from_file:
        try:
            with open(from_file) as f:
                payload = _json.load(f)
        except _json.JSONDecodeError as e:
            rprint(f"[red]Invalid JSON in {from_file}:[/red] {e}")
            raise typer.Exit(code=1)
        except FileNotFoundError:
            rprint(f"[red]File not found:[/red] {from_file}")
            raise typer.Exit(code=1)
    else:
        # --- Paste-first: parse SKILL.md locally if provided ---
        prefill: dict = {}
        skill_md_content: str | None = None
        script_content: str | None = None
        script_filename: str | None = None

        if skill_md:
            try:
                raw = Path(skill_md).read_text(encoding="utf-8")
            except FileNotFoundError:
                rprint(f"[red]SKILL.md not found:[/red] {skill_md}")
                raise typer.Exit(code=1)
            fm = _parse_frontmatter(raw)
            skill_md_content = raw
            prefill["name"] = fm.get("name", "")
            prefill["description"] = fm.get("description", "")
            cmd_field = fm.get("command", "")
            if isinstance(cmd_field, str) and cmd_field.strip():
                prefill["slash_command"] = cmd_field.strip().lstrip("/")
            if fm:
                rprint(
                    f"[green]✓ Parsed SKILL.md:[/green] name={prefill.get('name')!r}  "
                    f"description={str(prefill.get('description', ''))[:60]!r}"
                )

        if script:
            script_path_obj = Path(script)
            if not script_path_obj.exists():
                rprint(f"[red]Script file not found:[/red] {script}")
                raise typer.Exit(code=1)
            script_content = script_path_obj.read_text(encoding="utf-8")
            script_filename = script_path_obj.name
            rprint(f"[green]✓ Read script:[/green] {script_filename}")

        # Auto-detect delivery mode
        effective_delivery_mode = delivery_mode or (
            "registry_direct" if (skill_md_content and not git_url) else "git_fetch"
        )

        agents_input = text_input("Target agents (comma-separated)", default="")
        payload = {
            "name": text_input("Skill name", default=prefill.get("name", "")),
            "version": text_input("Version", default="1.0.0"),
            "description": text_input("Description", default=prefill.get("description", "")),
            "owner": text_input("Owner", default=config.load().get("user_name", "")),
            "task_type": select_one("Task type", VALID_SKILL_TASK_TYPES),
            "target_agents": [a.strip() for a in agents_input.split(",") if a.strip()],
            "delivery_mode": effective_delivery_mode,
        }
        if effective_delivery_mode == "git_fetch":
            payload["git_url"] = git_url or text_input("Git URL")
            payload["skill_path"] = text_input("Skill path in repo", default="/")
            payload["git_ref"] = git_ref or text_input("Git ref (branch/tag)", default="main")
        if prefill.get("slash_command"):
            payload["slash_command"] = prefill["slash_command"]
        if skill_md_content:
            payload["skill_md_content"] = skill_md_content
        if script_content:
            payload["script_content"] = script_content
            payload["script_filename"] = script_filename

    endpoint = "/api/v1/skills/draft" if draft else "/api/v1/skills/submit"
    label = "draft" if draft else "skill"
    with spinner(f"Saving {label}..."):
        result = client.post(endpoint, payload)
    validated = result.get("validated", False)
    validated_tag = "[green]✓ validated[/green]" if validated else "[yellow]unvalidated[/yellow]"
    rprint(f"[green]✓ {label.capitalize()} submitted![/green] ID: [bold]{result['id']}[/bold]  {validated_tag}")


# ── List / My ─────────────────────────────────────────────────────────────────


@skill_app.command(name="list")
def skill_list(
    task_type: str | None = typer.Option(None, "--task-type", "-t"),
    target_agent: str | None = typer.Option(None, "--target-agent"),
    search: str | None = typer.Option(None, "--search", "-s"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List approved skills in the registry.

    Shows only skills with approved status. Use --task-type, --target-agent,
    or --search to filter results. Row numbers from the output can be used
    as references in subsequent commands.

    Examples:
        observal registry skill list
        observal registry skill list --task-type coding
        observal registry skill list --target-agent claude-code --output json
        observal registry skill list --search "refactor"
    """
    params = {}
    if task_type:
        params["task_type"] = task_type
    if target_agent:
        params["target_agent"] = target_agent
    if search:
        params["search"] = search
    with spinner("Fetching skills..."):
        data = client.get("/api/v1/skills", params=params)
    if not data:
        rprint("[dim]No skills found.[/dim]")
        return
    config.save_last_results(data)
    if output == "json":
        output_json(data)
        return
    if output == "plain":
        for item in data:
            rprint(f"{item['id']}  {item['name']}  v{item.get('version', '?')}")
        return
    table = Table(title=f"Skills ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Version", style="green")
    table.add_column("Owner", style="dim")
    table.add_column("Status")
    table.add_column("ID", style="dim", max_width=12)
    for i, item in enumerate(data, 1):
        table.add_row(
            str(i),
            item["name"],
            item.get("version", ""),
            item.get("owner", ""),
            status_badge(item.get("status", "")),
            str(item["id"])[:8] + "…",
        )
    console.print(table)


@skill_app.command(name="my")
def skill_my(
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List your own skills across all statuses.

    Shows drafts, pending, approved, and rejected skills you submitted.
    Useful for tracking the review status of your submissions.

    Examples:
        observal registry skill my
        observal registry skill my --output json
    """
    with spinner("Fetching your skills..."):
        data = client.get("/api/v1/skills/my")
    if not data:
        rprint("[dim]You have no skills.[/dim]")
        return
    config.save_last_results(data)
    if output == "json":
        output_json(data)
        return
    if output == "plain":
        for item in data:
            rprint(f"{item['name']}  v{item.get('version', '?')}  {item.get('status', '')}")
        return
    table = Table(title=f"My Skills ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Version", style="green")
    table.add_column("Owner", style="dim")
    table.add_column("Status")
    table.add_column("ID", style="dim", max_width=12)
    for i, item in enumerate(data, 1):
        table.add_row(
            str(i),
            item["name"],
            item.get("version", ""),
            item.get("owner", ""),
            status_badge(item.get("status", "")),
            str(item["id"])[:8] + "…",
        )
    console.print(table)


# ── Show ──────────────────────────────────────────────────────────────────────


@skill_app.command(name="show")
def skill_show(
    skill_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show detailed information about a skill.

    Displays metadata including validation status, task type, git source,
    slash command, target agents, and timestamps. Accepts a UUID, name,
    row number from a previous list, or @alias.

    Examples:
        observal registry skill show my-skill
        observal registry skill show 1
        observal registry skill show @refactor-skill --output json
    """
    resolved = config.resolve_alias(skill_id)
    with spinner():
        item = client.get(f"/api/v1/skills/{resolved}")
    if output == "json":
        output_json(item)
        return
    console.print(
        kv_panel(
            f"{item['name']} v{item.get('version', '?')}",
            [
                ("Status", status_badge(item.get("status", ""))),
                ("Validated", "✓" if item.get("validated") else "✗"),
                ("Task Type", item.get("task_type", "N/A")),
                ("Delivery Mode", item.get("delivery_mode", "git_fetch")),
                ("Owner", item.get("owner", "N/A")),
                ("Git URL", item.get("git_url", "N/A")),
                ("Git Ref", item.get("git_ref") or "N/A"),
                ("Skill Path", item.get("skill_path", "/")),
                ("Script", item.get("script_filename") or "N/A"),
                ("Slash Command", f"/{item['slash_command']}" if item.get("slash_command") else "N/A"),
                ("Description", item.get("description", "")),
                ("Target Agents", ", ".join(item.get("target_agents", [])) or "N/A"),
                ("Created", relative_time(item.get("created_at"))),
                ("ID", f"[dim]{item['id']}[/dim]"),
            ],
            border_style="green",
        )
    )


# ── Install ────────────────────────────────────────────────────────────────────


def _sparse_clone_skill_dir(git_url: str, skill_path: str, git_ref: str, dest: Path) -> bool:
    """Sparse-clone only the skill subdirectory from a remote repo.

    Returns True on success, False if git is unavailable or the clone fails.
    Writes the full skill directory tree to *dest*.
    """
    import shutil

    # Guard against None values from API responses
    git_ref = git_ref or "main"
    skill_path = skill_path or "/"

    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False

    clean_path = skill_path.strip("/")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _run = lambda cmd, **kw: subprocess.run(  # noqa: E731
                cmd, cwd=tmp_path, check=True, capture_output=True, timeout=30, **kw
            )
            _run(["git", "init"])
            _run(["git", "remote", "add", "origin", git_url])
            _run(["git", "config", "core.sparseCheckout", "true"])
            _run(["git", "fetch", "--filter=blob:none", "--depth=1", "origin", git_ref])
            # Set sparse checkout path
            sparse_file = tmp_path / ".git" / "info" / "sparse-checkout"
            sparse_file.parent.mkdir(parents=True, exist_ok=True)
            sparse_file.write_text(f"{clean_path}/\n" if clean_path else "/\n")
            _run(["git", "checkout", f"origin/{git_ref}"])
            # Copy skill directory to dest
            src = tmp_path / clean_path if clean_path else tmp_path
            if not src.exists():
                return False
            shutil.copytree(src, dest, dirs_exist_ok=True)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


@skill_app.command(name="install")
def skill_install(
    skill_id: str = typer.Argument(..., help="Skill ID, name, row number, or @alias"),
    ide: str = typer.Option(..., "--ide", "-i", help="Target IDE"),
    scope: str = typer.Option("user", "--scope", "-s", help="Install scope: user (global, default) or project"),
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON only"),
    no_write: bool = typer.Option(False, "--no-write", help="Print config without writing files"),
):
    """Install a skill by fetching the full skill directory from git.

    Clones the skill directory (sparse checkout) from the configured git_url
    and writes it to the appropriate IDE skill path. Falls back to cached
    SKILL.md content if git clone fails.

    Scopes:
      --scope user (default): writes to ~/.<ide>/skills/<name>/ (global).
      --scope project: writes to .agents/skills/<name>/ in cwd, then
        symlinks into each IDE config dir found in the project.

    Examples:
        observal registry skill install my-skill --ide claude-code
        observal registry skill install @sk --ide kiro --scope project
        observal registry skill install 2 --ide cursor --raw > config.json
        observal registry skill install my-skill --ide gemini-cli --no-write
    """
    resolved = config.resolve_alias(skill_id)
    with spinner(f"Generating {ide} config..."):
        result = client.post(f"/api/v1/skills/{resolved}/install", {"ide": ide, "scope": scope})
    snippet = result.get("config_snippet", result)

    if raw:
        print(_json.dumps(snippet, indent=2))
        return

    skill_info = snippet.get("skill", {})

    if not no_write:
        delivery_mode = skill_info.get("delivery_mode", "git_fetch")
        if delivery_mode == "registry_direct":
            install_skill_registry_direct(
                name=skill_info.get("name", "skill"),
                skill_md_content=skill_info.get("skill_md_content"),
                script_content=skill_info.get("script_content"),
                script_filename=skill_info.get("script_filename"),
                ide=ide,
                scope=scope,
            )
        else:
            install_skill_from_git(
                name=skill_info.get("name", "skill"),
                git_url=skill_info.get("git_url"),
                skill_path=skill_info.get("skill_path", "/"),
                git_ref=skill_info.get("git_ref", "main"),
                ide=ide,
                scope=scope,
                skill_md_content=skill_info.get("skill_md_content"),
            )
    else:
        rprint("[dim]Skill install skipped (--no-write)[/dim]")

    rprint(f"\n[bold]Config for {ide}:[/bold]\n")
    console.print_json(_json.dumps(snippet, indent=2))


# Agent config dirs to check for symlinking (canonical name → dir name)
_AGENT_SKILL_DIRS: list[tuple[str, str]] = [
    ("claude-code", ".claude"),
    ("cursor", ".cursor"),
    ("kiro", ".kiro"),
    ("gemini-cli", ".gemini"),
    ("opencode", ".opencode"),
]

# User-scope skill directories per IDE (global install locations)
_USER_SKILL_DIRS: dict[str, str] = {
    "claude-code": "~/.claude/skills",
    "kiro": "~/.kiro/skills",
    "gemini-cli": "~/.gemini/skills",
    "opencode": "~/.config/opencode/skills",
    "cursor": "~/.cursor/rules",
    "copilot": "~/.copilot/skills",
    "pi": "~/.pi/agent/skills",
}


def _user_skill_dest(ide: str, skill_name: str) -> Path:
    """Resolve the user-scope (global) install path for a skill."""
    ide_key = ide.replace("_", "-")
    base = _USER_SKILL_DIRS.get(ide_key, "~/.agents/skills")
    expanded = Path(base.replace("~", str(Path.home())))
    return expanded / skill_name


def install_skill_registry_direct(
    *,
    name: str,
    skill_md_content: str | None,
    script_content: str | None = None,
    script_filename: str | None = None,
    ide: str = "claude-code",
    scope: str = "user",
    cwd: Path | None = None,
) -> Path | None:
    """Install a registry_direct skill: write SKILL.md and optional script.

    Writes to <dest>/<name>/SKILL.md and <dest>/<name>/scripts/<script_filename>.
    Returns the destination Path on success, None on failure.
    """
    skill_name = _sanitize_name(name)

    if scope == "user":
        dest = _user_skill_dest(ide, skill_name)
    else:
        base = (cwd or Path.cwd()) / ".agents" / "skills"
        dest = base / skill_name
        if not _is_path_safe(dest, base):
            rprint(f"[red]\u2717 Unsafe skill name (path traversal detected):[/red] {skill_name!r}")
            return None

    if not skill_md_content:
        rprint("[yellow]\u26a0 No SKILL.md content available to write.[/yellow]")
        return None

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
    rprint(f"[green]\u2713 Wrote skill file:[/green] {dest / 'SKILL.md'}")

    if script_content and script_filename:
        scripts_dir = dest / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_path = scripts_dir / script_filename
        if not _is_path_safe(script_path, scripts_dir):
            rprint(f"[red]\u2717 Unsafe script filename (path traversal):[/red] {script_filename!r}")
        else:
            script_path.write_text(script_content, encoding="utf-8")
            # Make executable if it looks like a script
            if script_filename.endswith((".sh", ".bash", ".py", ".rb")):
                import os

                os.chmod(script_path, 0o755)
            rprint(f"[green]\u2713 Wrote script:[/green] {script_path}")

    if scope == "project":
        _symlink_for_ides(cwd or Path.cwd(), dest, skill_name)

    return dest


def install_skill_from_git(
    *,
    name: str,
    git_url: str | None,
    skill_path: str = "/",
    git_ref: str = "main",
    ide: str = "claude-code",
    scope: str = "user",
    skill_md_content: str | None = None,
    cwd: Path | None = None,
) -> Path | None:
    """Core skill install logic — clone full directory from git.

    Used by both `observal skill install` and `observal pull` (for agent skills).

    Returns the destination Path on success, None on failure.
    """
    skill_name = _sanitize_name(name)

    if scope == "user":
        dest = _user_skill_dest(ide, skill_name)
    else:
        base = (cwd or Path.cwd()) / ".agents" / "skills"
        dest = base / skill_name
        if not _is_path_safe(dest, base):
            rprint(f"[red]\u2717 Unsafe skill name (path traversal detected):[/red] {skill_name!r}")
            return None

    wrote_full_dir = False

    if git_url:
        dest.mkdir(parents=True, exist_ok=True)
        wrote_full_dir = _sparse_clone_skill_dir(git_url, skill_path, git_ref, dest)
        if wrote_full_dir:
            rprint(f"[green]\u2713 Skill directory written:[/green] {dest}")
            if scope == "project":
                _symlink_for_ides(cwd or Path.cwd(), dest, skill_name)
            return dest
        rprint("[yellow]\u26a0 git clone failed.[/yellow] Falling back to SKILL.md cache.")

    # Fallback: write cached SKILL.md only
    if skill_md_content:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
        rprint(f"[green]\u2713 Wrote skill file (cached):[/green] {dest / 'SKILL.md'}")
        return dest

    rprint("[yellow]\u26a0 No skill content available to write.[/yellow]")
    return None


def _symlink_for_ides(cwd: Path, canonical: Path, skill_name: str) -> None:
    """Create .<agent>/skills/<name>/ symlinks for every IDE config dir that exists."""
    for _ide, agent_dir in _AGENT_SKILL_DIRS:
        agent_root = cwd / agent_dir
        if not agent_root.exists():
            continue
        skills_dir = agent_root / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        link = skills_dir / skill_name
        if link.exists() or link.is_symlink():
            continue
        try:
            link.symlink_to(canonical.resolve())
            rprint(f"[dim]  → symlinked {link} → {canonical}[/dim]")
        except OSError:
            pass  # Non-fatal — Windows without dev mode, etc.


# ── Edit ─────────────────────────────────────────────────────────────────────


@skill_app.command(name="edit")
def skill_edit(
    skill_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Load updates from JSON file"),
    name: str | None = typer.Option(None, "--name", "-n", help="New listing name"),
    description: str | None = typer.Option(None, "--description", "-d", help="New description"),
    version: str | None = typer.Option(None, "--version", "-v", help="New version string"),
    task_type: str | None = typer.Option(None, "--task-type", "-t", help="New task type"),
    git_url: str | None = typer.Option(None, "--git-url", help="New git URL"),
    git_ref: str | None = typer.Option(None, "--git-ref", help="New git ref"),
):
    """Edit a draft, rejected, or pending skill submission.

    Updates fields on a skill that has not yet been approved. You can
    provide individual field options or load all updates from a JSON file.
    Acquires an edit lock to prevent concurrent modifications.

    Examples:
        observal registry skill edit my-skill --description "Better desc"
        observal registry skill edit abc123 --from-file updates.json
        observal registry skill edit @sk --git-url https://github.com/org/new-repo
        observal registry skill edit 2 --version 2.0.0 --task-type debugging
    """
    resolved = config.resolve_alias(skill_id)
    if from_file:
        try:
            with open(from_file) as f:
                updates = _json.load(f)
        except _json.JSONDecodeError as e:
            rprint(f"[red]Invalid JSON in {from_file}:[/red] {e}")
            raise typer.Exit(code=1)
        except FileNotFoundError:
            rprint(f"[red]File not found:[/red] {from_file}")
            raise typer.Exit(code=1)
    else:
        updates = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if version is not None:
            updates["version"] = version
        if task_type is not None:
            updates["task_type"] = task_type
        if git_url is not None:
            updates["git_url"] = git_url
        if git_ref is not None:
            updates["git_ref"] = git_ref

    if not updates:
        rprint(
            "[yellow]No changes specified.[/yellow] "
            "Use --from-file or field options (--name, --description, --git-url, etc.)"
        )
        raise typer.Exit(code=1)

    try:
        client.post(f"/api/v1/skills/{resolved}/start-edit")
    except Exception as exc:
        if "409" in str(exc) or "currently being edited" in str(exc):
            rprint(f"[red]✗ Cannot edit:[/red] {exc}")
            raise typer.Exit(code=1)
    try:
        with spinner("Saving changes..."):
            result = client.put(f"/api/v1/skills/{resolved}/draft", updates)
        rprint(f"[green]✓ Updated {result['name']}[/green] (status: {result.get('status', 'unknown')})")
    except Exception as exc:
        try:
            client.post(f"/api/v1/skills/{resolved}/cancel-edit")
        except Exception:
            pass
        rprint(f"[red]Failed to update:[/red] {exc}")
        raise typer.Exit(code=1)


# ── Delete ────────────────────────────────────────────────────────────────────


@skill_app.command(name="delete")
def skill_delete(
    skill_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a skill from the registry.

    Permanently removes the skill. Skills you own can be deleted regardless
    of status. Requires confirmation unless --yes is passed.

    Examples:
        observal registry skill delete my-skill
        observal registry skill delete abc123 --yes
        observal registry skill delete @old-skill -y
    """
    resolved = config.resolve_alias(skill_id)
    if not yes:
        with spinner():
            item = client.get(f"/api/v1/skills/{resolved}")
        if not typer.confirm(f"Delete [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    with spinner("Deleting..."):
        client.delete(f"/api/v1/skills/{resolved}")
    rprint(f"[green]✓ Deleted {resolved}[/green]")
