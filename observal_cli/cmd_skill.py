# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Skill registry CLI commands."""

from __future__ import annotations

import json as _json
import re
import subprocess
import tempfile
from contextlib import nullcontext, redirect_stdout
from io import StringIO
from pathlib import Path

import typer
from packaging.version import InvalidVersion, Version
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.constants import HARNESS_CAPABILITIES, VALID_HARNESSES, VALID_SKILL_TASK_TYPES
from observal_cli.errors import ErrorCategory, fail
from observal_cli.prompts import select_one, text_input
from observal_cli.render import (
    OutputMode,
    console,
    display_name,
    esc,
    handle,
    kv_panel,
    output_json,
    relative_time,
    spinner,
    status_badge,
)
from observal_cli.shared.utils import sanitize_name as _sanitize_name

skill_app = typer.Typer(
    help=(
        "Skill registry commands\n\n"
        "Examples:\n"
        "  observal registry skill list\n"
        "  observal registry skill show alice/my-skill\n"
        "  observal registry skill install alice/my-skill --harness claude-code"
    )
)


def register_skill(app: typer.Typer):
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


def _validate_skill_fields(payload: dict, operation: str) -> None:
    task_type = payload.get("task_type")
    if task_type is not None and task_type not in VALID_SKILL_TASK_TYPES:
        fail(
            ErrorCategory.VALIDATION,
            f"Unknown skill task type: {task_type}.",
            operation=operation,
            resource="task type",
            remediation=f"Choose one of: {', '.join(VALID_SKILL_TASK_TYPES)}.",
        )
    harnesses = payload.get("supported_harnesses")
    if harnesses is not None:
        bad_harnesses = (
            [item for item in harnesses if item not in VALID_HARNESSES]
            if isinstance(harnesses, list)
            else [str(harnesses)]
        )
        if bad_harnesses:
            fail(
                ErrorCategory.VALIDATION,
                f"Unknown harness: {bad_harnesses[0]}.",
                operation=operation,
                resource="supported harnesses",
                remediation=f"Choose from: {', '.join(VALID_HARNESSES)}.",
            )
    version = payload.get("version")
    if version is not None:
        try:
            Version(str(version))
        except InvalidVersion as error:
            fail(
                ErrorCategory.VALIDATION,
                "The skill version is invalid.",
                operation=operation,
                resource=str(version),
                remediation="Provide a valid version and retry.",
                detail=repr(error),
            )


# ── Submit ────────────────────────────────────────────────────────────────────


@skill_app.command(name="submit")
def skill_submit(
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Create from JSON file"),
    skill_md: str | None = typer.Option(None, "--skill-md", help="Path to SKILL.md to paste (auto-fills fields)"),
    git_url: str | None = typer.Option(None, "--git-url", help="Git repository URL"),
    git_ref: str | None = typer.Option(None, "--git-ref", help="Branch or tag (default: main)"),
    script: str | None = typer.Option(None, "--script", help="Path to script file (registry_direct mode)"),
    delivery_mode: str | None = typer.Option(None, "--delivery-mode", help="Delivery: git_fetch or registry_direct"),
    name: str | None = typer.Option(None, "--name", "-n", help="Skill name"),
    version: str | None = typer.Option(None, "--version", "-v", help="Version (default: 1.0.0)"),
    description: str | None = typer.Option(None, "--description", "-d", help="Short description"),
    task_type: str | None = typer.Option(None, "--task-type", "-t", help="Task type"),
    target_agent: list[str] | None = typer.Option(None, "--target-agent", help="Target agent (repeatable)"),
    skill_path: str | None = typer.Option(None, "--skill-path", help="Skill path in repo"),
    slash_command: str | None = typer.Option(None, "--slash-command", help="Slash command name"),
    supported_harnesses: list[str] | None = typer.Option(None, "--harness", help="Supported harness (repeatable)"),
    draft: bool = typer.Option(False, "--draft", help="Save as draft instead of submitting for review"),
    submit_draft: str | None = typer.Option(None, "--submit", help="Submit a draft for review (skill ID)"),
    team: str | None = typer.Option(None, "--team", help="Teamspace UUID or handle"),
    visibility: str | None = typer.Option(None, "--visibility", help="Visibility: public or team"),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
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
        observal registry skill submit --skill-md ./SKILL.md --git-url https://github.com/org/repo
        observal registry skill submit --skill-md ./SKILL.md --script ./run.sh \
          --delivery-mode registry_direct --name my-skill --description "My skill" --output json
    """
    human_output = output != "json"
    if human_output:
        rprint("[dim]Note: Only submit components you created or represent.[/dim]")
    if draft and submit_draft:
        fail(
            ErrorCategory.VALIDATION,
            "Draft creation and draft submission cannot be requested together.",
            operation="Submit skill",
            resource="submit options",
            remediation="Choose either draft creation or draft submission and retry.",
        )

    if submit_draft:
        resolved = client.resolve_registry_reference("skill", submit_draft)
        submit_context = nullcontext() if output == "json" else spinner("Submitting draft for review...")
        with submit_context:
            result = client.post(f"/api/v1/skills/{resolved}/submit")
        if output == "json":
            output_json(result)
        else:
            rprint(f"[green]✓ Draft submitted for review![/green] ID: [bold]{esc(result['id'])}[/bold]")
        return

    if from_file:
        try:
            with open(from_file) as f:
                payload = _json.load(f)
        except _json.JSONDecodeError as error:
            fail(
                ErrorCategory.VALIDATION,
                "The skill submission file is not valid JSON.",
                operation="Submit skill",
                resource=from_file,
                remediation="Correct the JSON and retry.",
                detail=repr(error),
            )
        except FileNotFoundError as error:
            fail(
                ErrorCategory.NOT_FOUND,
                "The skill submission file was not found.",
                operation="Submit skill",
                resource=from_file,
                remediation="Provide an existing JSON file and retry.",
                detail=repr(error),
            )
        if not isinstance(payload, dict):
            fail(
                ErrorCategory.VALIDATION,
                "The skill submission file must contain a JSON object.",
                operation="Submit skill",
                resource=from_file,
                remediation="Replace the file contents with a JSON object and retry.",
            )
        _validate_skill_fields(payload, "Submit skill")
    else:
        # --- Paste-first: parse SKILL.md locally if provided ---
        prefill: dict = {}
        skill_md_content: str | None = None
        script_content: str | None = None
        script_filename: str | None = None

        if skill_md:
            try:
                raw = Path(skill_md).read_text(encoding="utf-8")
            except FileNotFoundError as error:
                fail(
                    ErrorCategory.NOT_FOUND,
                    "The SKILL.md file was not found.",
                    operation="Submit skill",
                    resource=skill_md,
                    remediation="Provide an existing SKILL.md file and retry.",
                    detail=repr(error),
                )
            fm = _parse_frontmatter(raw)
            skill_md_content = raw
            prefill["name"] = fm.get("name", "")
            prefill["description"] = fm.get("description", "")
            cmd_field = fm.get("command", "")
            if isinstance(cmd_field, str) and cmd_field.strip():
                prefill["slash_command"] = cmd_field.strip().lstrip("/")
            if fm and human_output:
                rprint(
                    f"[green]✓ Parsed SKILL.md:[/green] name={esc(repr(prefill.get('name')))}  "
                    f"description={esc(repr(str(prefill.get('description', ''))[:60]))}"
                )

        if script:
            script_path_obj = Path(script)
            if not script_path_obj.is_file():
                fail(
                    ErrorCategory.NOT_FOUND,
                    "The skill script file was not found.",
                    operation="Submit skill",
                    resource=script,
                    remediation="Provide an existing script file and retry.",
                )
            script_content = script_path_obj.read_text(encoding="utf-8")
            script_filename = script_path_obj.name
            if human_output:
                rprint(f"[green]✓ Read script:[/green] {esc(script_filename)}")

        # Auto-detect delivery mode
        effective_delivery_mode = delivery_mode or (
            "registry_direct" if (skill_md_content and not git_url) else "git_fetch"
        )

        flag_mode = any(
            x is not None
            for x in (name, version, description, task_type, skill_path, slash_command, supported_harnesses)
        ) or bool(target_agent)
        if output == "json" and not flag_mode:
            fail(
                ErrorCategory.VALIDATION,
                "JSON mode requires explicit skill fields.",
                operation="Submit skill",
                resource="submit options",
                remediation="Provide name, description, task type, and the selected delivery source.",
            )
        if flag_mode:
            _name = name or prefill.get("name", "")
            _description = description or prefill.get("description", "")
            if not _name or not _description:
                fail(
                    ErrorCategory.VALIDATION,
                    "Skill name and description are required without prompts.",
                    operation="Submit skill",
                    resource="skill payload",
                    remediation="Provide both name and description and retry.",
                )
            payload = {
                "name": _name,
                "version": version or "1.0.0",
                "description": _description,
                "owner": config.load().get("username", ""),
                "task_type": task_type or "general",
                "target_agents": target_agent or [],
                "delivery_mode": effective_delivery_mode,
                "supported_harnesses": supported_harnesses or [],
            }
        else:
            agents_input = text_input("Target agents (comma-separated)", default="")
            payload = {
                "name": text_input("Skill name", default=prefill.get("name", "")),
                "version": text_input("Version", default="1.0.0"),
                "description": text_input("Description", default=prefill.get("description", "")),
                "owner": config.load().get("username", ""),
                "task_type": select_one("Task type", VALID_SKILL_TASK_TYPES),
                "target_agents": [a.strip() for a in agents_input.split(",") if a.strip()],
                "delivery_mode": effective_delivery_mode,
            }
        _validate_skill_fields(payload, "Submit skill")
        if effective_delivery_mode == "git_fetch":
            if flag_mode and not git_url:
                fail(
                    ErrorCategory.VALIDATION,
                    "A Git URL is required for git-fetch skills.",
                    operation="Submit skill",
                    resource="Git URL",
                    remediation="Provide a Git URL or choose registry-direct delivery.",
                )
            payload["git_url"] = git_url or text_input("Git URL")
            payload["skill_path"] = skill_path or ("/" if flag_mode else text_input("Skill path in repo", default="/"))
            payload["git_ref"] = git_ref or (
                "main" if flag_mode else text_input("Git ref (branch/tag)", default="main")
            )
        if slash_command or prefill.get("slash_command"):
            payload["slash_command"] = slash_command or prefill["slash_command"]
        if skill_md_content:
            payload["skill_md_content"] = skill_md_content
        if script_content:
            payload["script_content"] = script_content
            payload["script_filename"] = script_filename

    client.add_publish_target(payload, team, visibility)
    endpoint = "/api/v1/skills/draft" if draft else "/api/v1/skills/submit"
    label = "draft" if draft else "skill"
    submit_context = nullcontext() if output == "json" else spinner(f"Saving {label}...")
    with submit_context:
        result = client.post(endpoint, payload)
    if output == "json":
        output_json(result)
        return
    validated = result.get("validated", False)
    validated_tag = "[green]✓ validated[/green]" if validated else "[yellow]unvalidated[/yellow]"
    rprint(f"[green]✓ {label.capitalize()} submitted![/green] ID: [bold]{esc(result['id'])}[/bold]  {validated_tag}")
    rprint(f"  Install: [cyan]observal registry skill install {esc(client.canonical_name(result))}[/cyan]")


# ── List / My ─────────────────────────────────────────────────────────────────


@skill_app.command(name="list")
def skill_list(
    task_type: str | None = typer.Option(None, "--task-type", "-t"),
    target_agent: str | None = typer.Option(None, "--target-agent"),
    harness: str | None = typer.Option(None, "--harness", help="Only skills supporting this harness"),
    search: str | None = typer.Option(None, "--search", "-s"),
    namespace: str | None = typer.Option(None, "--namespace", help="Filter by user or team namespace"),
    team: str | None = typer.Option(None, "--team", help="Only items owned by this teamspace"),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
):
    """List approved skills in the registry.

    Shows only skills with approved status. Use --task-type, --target-agent,
    or --search to filter results. Row numbers from the output can be used
    as references in subsequent commands.

    Examples:
        observal registry skill list
        observal registry skill list --task-type code-generation
        observal registry skill list --target-agent claude-code --output json
    """
    if task_type and task_type not in VALID_SKILL_TASK_TYPES:
        fail(
            ErrorCategory.VALIDATION,
            f"Unknown skill task type: {task_type}.",
            operation="List skills",
            resource="task type filter",
            remediation=f"Choose one of: {', '.join(VALID_SKILL_TASK_TYPES)}.",
        )
    if harness and (harness not in VALID_HARNESSES or "skills" not in HARNESS_CAPABILITIES.get(harness, set())):
        fail(
            ErrorCategory.VALIDATION,
            f"Harness {harness} does not support skills.",
            operation="List skills",
            resource="harness filter",
            remediation="Choose a harness with skill support.",
        )
    params = {}
    if task_type:
        params["task_type"] = task_type
    if target_agent:
        params["target_agent"] = target_agent
    if harness:
        params["harness"] = harness
    if search:
        params["search"] = search
    if namespace:
        params["namespace"] = namespace.lstrip("@").lower()
    if team:
        params["team_id"] = client.resolve_team_id(team)
    fetch_ctx = nullcontext() if output == "json" else spinner("Fetching skills...")
    with fetch_ctx:
        data = client.get("/api/v1/skills", params=params)
    if not data:
        config.save_last_results([], "skill")
        if output == "json":
            output_json([])
        else:
            rprint("[dim]No skills found.[/dim]")
        return
    config.save_last_results(data, "skill")
    if output == "json":
        output_json(data)
        return
    table = Table(title=f"Skills ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Version", style="green")
    table.add_column("Namespace", style="dim")
    table.add_column("Status")
    table.add_column("ID", style="dim", max_width=12)
    for i, item in enumerate(data, 1):
        table.add_row(
            str(i),
            esc(display_name(item)),
            esc(item.get("version", "")),
            esc(handle(item)),
            status_badge(item.get("status", "")),
            esc(str(item["id"])[:8] + "…"),
        )
    console.print(table)


@skill_app.command(name="my")
def skill_my(
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
):
    """List your own skills across all statuses.

    Shows drafts, pending, approved, and rejected skills you submitted.
    Useful for tracking the review status of your submissions.

    Examples:
        observal registry skill my
        observal registry skill my --output json
    """
    fetch_ctx = nullcontext() if output == "json" else spinner("Fetching your skills...")
    with fetch_ctx:
        data = client.get("/api/v1/skills/my")
    if not data:
        config.save_last_results([], "skill")
        if output == "json":
            output_json([])
        else:
            rprint("[dim]You have no skills.[/dim]")
        return
    config.save_last_results(data, "skill")
    if output == "json":
        output_json(data)
        return
    table = Table(title=f"My Skills ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Version", style="green")
    table.add_column("Namespace", style="dim")
    table.add_column("Status")
    table.add_column("ID", style="dim", max_width=12)
    for i, item in enumerate(data, 1):
        table.add_row(
            str(i),
            esc(display_name(item)),
            esc(item.get("version", "")),
            esc(handle(item)),
            status_badge(item.get("status", "")),
            esc(str(item["id"])[:8] + "…"),
        )
    console.print(table)


# ── Show ──────────────────────────────────────────────────────────────────────


@skill_app.command(name="show")
def skill_show(
    skill_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    output: OutputMode = typer.Option("table", "--output", "-o"),
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
    resolved = client.resolve_registry_reference("skill", skill_id)
    fetch_ctx = nullcontext() if output == "json" else spinner()
    with fetch_ctx:
        item = client.get(f"/api/v1/skills/{resolved}")
    if output == "json":
        output_json(item)
        return
    console.print(
        kv_panel(
            f"{esc(display_name(item))} v{esc(item.get('version', '?'))}",
            [
                ("Status", status_badge(item.get("status", ""))),
                ("Validated", "✓" if item.get("validated") else "✗"),
                ("Task Type", esc(item.get("task_type", "N/A"))),
                ("Delivery Mode", esc(item.get("delivery_mode", "git_fetch"))),
                ("Namespace", esc(handle(item) or "N/A")),
                ("Git URL", esc(item.get("git_url", "N/A"))),
                ("Git Ref", esc(item.get("git_ref") or "N/A")),
                ("Skill Path", esc(item.get("skill_path", "/"))),
                ("Script", esc(item.get("script_filename") or "N/A")),
                ("Slash Command", esc(f"/{item['slash_command']}" if item.get("slash_command") else "N/A")),
                ("Description", esc(item.get("description", ""))),
                ("Target Agents", esc(", ".join(item.get("target_agents", [])) or "N/A")),
                ("Created", esc(relative_time(item.get("created_at")))),
                ("ID", f"[dim]{esc(item['id'])}[/dim]"),
            ],
            border_style="green",
        )
    )


# ── Install ────────────────────────────────────────────────────────────────────


def _normalize_skill_path(skill_path: str | None) -> str:
    clean_path = (skill_path or "/").strip("/")
    if clean_path.casefold() == "skill.md":
        return ""
    if clean_path.casefold().endswith("/skill.md"):
        return clean_path.rsplit("/", 1)[0]
    return clean_path


def _sparse_clone_skill_dir(git_url: str, skill_path: str, git_ref: str, dest: Path) -> bool:
    """Sparse-clone only the skill subdirectory from a remote repo.

    Returns True on success, False if git is unavailable or the clone fails.
    Writes the full skill directory tree to *dest*.
    """
    import shutil

    git_ref = git_ref or "main"

    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False

    clean_path = _normalize_skill_path(skill_path)

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
            _run(["git", "checkout", "FETCH_HEAD"])
            # Copy skill directory to dest
            src = tmp_path / clean_path if clean_path else tmp_path
            if not src.exists():
                return False
            shutil.copytree(src, dest, dirs_exist_ok=True)
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


@skill_app.command(name="install")
def skill_install(
    skill_id: str = typer.Argument(..., help="Skill ID, name, row number, or @alias"),
    harness: str = typer.Option(..., "--harness", "-i", help="Target harness"),
    scope: str = typer.Option("user", "--scope", "-s", help="Install scope: user (global, default) or project"),
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON only"),
    no_write: bool = typer.Option(False, "--no-write", help="Print config without writing files"),
    version: str | None = typer.Option(
        None, "--version", "-V", help="Install a specific version (e.g. '1.0.0'). Defaults to latest."
    ),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
):
    """Install a skill by fetching the full skill directory from git.

    Clones the skill directory (sparse checkout) from the configured git_url
    and writes it to the appropriate harness skill path.

    Scopes:
      --scope user (default): writes to the harness's global skills directory.
      --scope project: writes to .agents/skills/<name>/ in cwd, then
        symlinks into each harness config dir found in the project.

    Examples:
        observal registry skill install my-skill --harness claude-code
        observal registry skill install @sk --harness kiro --scope project
        observal registry skill install 2 --harness cursor --raw > config.json
    """
    if raw and output == "json":
        fail(
            ErrorCategory.VALIDATION,
            "Raw config output and JSON operation output cannot be combined.",
            operation="Install skill",
            resource="output options",
            remediation="Choose either raw config output or JSON operation output.",
        )
    if scope not in {"user", "project"}:
        fail(
            ErrorCategory.VALIDATION,
            f"Unknown skill scope: {scope}.",
            operation="Install skill",
            resource="scope",
            remediation="Choose user or project.",
        )
    if harness not in VALID_HARNESSES or "skills" not in HARNESS_CAPABILITIES.get(harness, set()):
        fail(
            ErrorCategory.VALIDATION,
            f"Harness {harness} does not support skills.",
            operation="Install skill",
            resource="harness",
            remediation="Choose a harness with skill support.",
        )
    if version:
        try:
            Version(version)
        except InvalidVersion as error:
            fail(
                ErrorCategory.VALIDATION,
                "The requested skill version is invalid.",
                operation="Install skill",
                resource=version,
                remediation="Provide a valid version and retry.",
                detail=repr(error),
            )
    machine_output = raw or output == "json"
    resolved = client.resolve_registry_reference("skill", skill_id)
    listing = client.get(f"/api/v1/skills/{resolved}")
    from observal_cli.lockfile import local_registry_name

    directory = str(Path.cwd()) if scope == "project" else None
    local_name = local_registry_name(
        harness,
        "skill",
        listing["namespace"],
        listing["slug"],
        scope=scope,
        directory=directory,
    )
    install_context = nullcontext() if machine_output else spinner(f"Generating {harness} config...")
    with install_context:
        install_body = {"harness": harness, "scope": scope, "local_name": local_name}
        if version:
            install_body["version"] = version
        result = client.post(f"/api/v1/skills/{resolved}/install", install_body)
    snippet = result.get("config_snippet", result)

    if raw:
        print(_json.dumps(snippet, indent=2))
        return

    skill_info = snippet.get("skill", {})
    if not isinstance(skill_info, dict):
        fail(
            ErrorCategory.UNAVAILABLE,
            "The registry returned an invalid skill installation response.",
            operation="Install skill",
            resource=skill_id,
            remediation="Check server health and version compatibility, then retry.",
        )

    installed_path: Path | None = None
    if not no_write:
        write_context = redirect_stdout(StringIO()) if output == "json" else nullcontext()
        with write_context:
            delivery_mode = skill_info.get("delivery_mode", "git_fetch")
            if delivery_mode == "registry_direct":
                installed_path = install_skill_registry_direct(
                    name=skill_info.get("name", "skill"),
                    skill_md_content=skill_info.get("skill_md_content"),
                    script_content=skill_info.get("script_content"),
                    script_filename=skill_info.get("script_filename"),
                    harness=harness,
                    scope=scope,
                )
            else:
                installed_path = install_skill_from_git(
                    name=skill_info.get("name", "skill"),
                    git_url=skill_info.get("git_url"),
                    skill_path=skill_info.get("skill_path", "/"),
                    git_ref=skill_info.get("git_ref", "main"),
                    harness=harness,
                    scope=scope,
                    skill_md_content=skill_info.get("skill_md_content"),
                )
        if installed_path is None:
            fail(
                ErrorCategory.UNAVAILABLE,
                "The skill content could not be installed.",
                operation="Install skill",
                resource=skill_id,
                remediation="Check the skill source and local filesystem, then retry.",
            )

        from observal_cli.lockfile import upsert_standalone

        try:
            upsert_standalone(
                harness,
                component_type="skill",
                name=skill_info.get("name", resolved),
                component_id=str(skill_info.get("id", resolved)),
                version=version or skill_info.get("version") or skill_info.get("latest_version"),
                scope=scope,
                directory=directory,
                namespace=listing.get("namespace"),
                slug=listing.get("slug"),
                local_name=local_name,
            )
        except PermissionError as error:
            fail(
                ErrorCategory.PERMISSION,
                "The skill was written but its installed state could not be recorded.",
                operation="Install skill",
                resource="installed-state lockfile",
                remediation="Check lockfile ownership and permissions, then retry.",
                detail=repr(error),
            )
        except (OSError, RuntimeError) as error:
            fail(
                ErrorCategory.UNAVAILABLE,
                "The skill was written but its installed state could not be recorded.",
                operation="Install skill",
                resource="installed-state lockfile",
                remediation="Check local storage and retry.",
                detail=repr(error),
            )
    elif output != "json":
        rprint("[dim]Skill install skipped (no-write mode).[/dim]")

    if output == "json":
        output_json(
            {
                **result,
                "write_performed": not no_write,
                "installed_path": str(installed_path) if installed_path else None,
            }
        )
        return

    for warning in result.get("warnings") or []:
        rprint(f"\n[yellow]Warning:[/yellow] {esc(warning)}")

    rprint(f"\n[bold]Config for {esc(harness)}:[/bold]\n")
    console.print_json(_json.dumps(snippet, indent=2))


# Harness config dirs to check for symlinking (canonical name → dir name)
_HARNESS_SKILL_DIRS: list[tuple[str, str]] = [
    ("claude-code", ".claude"),
    ("cursor", ".cursor"),
    ("kiro", ".kiro"),
    ("opencode", ".opencode"),
]

# User-scope skill directories per harness (global install locations)
_USER_SKILL_DIRS: dict[str, str] = {
    "claude-code": "~/.claude/skills",
    "kiro": "~/.kiro/skills",
    "opencode": "~/.config/opencode/skills",
    "cursor": "~/.cursor/rules",
    "copilot": "~/.copilot/skills",
    "pi": "~/.pi/agent/skills",
}


def _user_skill_dest(harness: str, skill_name: str) -> Path:
    """Resolve the user-scope (global) install path for a skill."""
    harness_key = harness.replace("_", "-")
    base = _USER_SKILL_DIRS.get(harness_key, "~/.agents/skills")
    expanded = Path(base.replace("~", str(Path.home())))
    return expanded / skill_name


def install_skill_registry_direct(
    *,
    name: str,
    skill_md_content: str | None,
    script_content: str | None = None,
    script_filename: str | None = None,
    harness: str = "claude-code",
    scope: str = "user",
    ide: str | None = None,
    cwd: Path | None = None,
    dest: Path | None = None,
) -> Path | None:
    """Install a registry_direct skill: write SKILL.md and optional script.

    Writes to <dest>/<name>/SKILL.md and <dest>/<name>/scripts/<script_filename>.
    Returns the destination Path on success, None on failure.
    """
    skill_name = _sanitize_name(name)
    custom_dest = dest is not None
    target_harness = ide or harness

    if dest is None:
        if scope == "user":
            dest = _user_skill_dest(target_harness, skill_name)
        else:
            base = (cwd or Path.cwd()) / ".agents" / "skills"
            dest = base / skill_name
            if not _is_path_safe(dest, base):
                rprint(f"[red]✗ Unsafe skill name (path traversal detected):[/red] {esc(repr(skill_name))}")
                return None

    if not skill_md_content:
        rprint("[yellow]\u26a0 No SKILL.md content available to write.[/yellow]")
        return None

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
    rprint(f"[green]\u2713 Wrote skill file:[/green] {esc(dest / 'SKILL.md')}")

    if script_content and script_filename:
        scripts_dir = dest / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_path = scripts_dir / script_filename
        if not _is_path_safe(script_path, scripts_dir):
            rprint(f"[red]\u2717 Unsafe script filename (path traversal):[/red] {esc(repr(script_filename))}")
        else:
            script_path.write_text(script_content, encoding="utf-8")
            # Make executable if it looks like a script
            if script_filename.endswith((".sh", ".bash", ".py", ".rb")):
                import os

                os.chmod(script_path, 0o755)
            rprint(f"[green]\u2713 Wrote script:[/green] {esc(script_path)}")

    if scope == "project" and not custom_dest:
        _symlink_for_harnesses(cwd or Path.cwd(), dest, skill_name)

    return dest


def install_skill_from_git(
    *,
    name: str,
    git_url: str | None,
    skill_path: str = "/",
    git_ref: str = "main",
    harness: str = "claude-code",
    scope: str = "user",
    ide: str | None = None,
    skill_md_content: str | None = None,
    cwd: Path | None = None,
    dest: Path | None = None,
) -> Path | None:
    """Core skill install logic - clone full directory from git.

    Used by both `observal skill install` and `observal pull` (for agent skills).

    Returns the destination Path on success, None on failure.
    """
    skill_name = _sanitize_name(name)
    custom_dest = dest is not None
    target_harness = ide or harness

    if dest is None:
        if scope == "user":
            dest = _user_skill_dest(target_harness, skill_name)
        else:
            base = (cwd or Path.cwd()) / ".agents" / "skills"
            dest = base / skill_name
            if not _is_path_safe(dest, base):
                rprint(f"[red]✗ Unsafe skill name (path traversal detected):[/red] {esc(repr(skill_name))}")
                return None

    if not git_url:
        rprint("[red]\u2717 Git URL is required for git-fetch skill installation.[/red]")
        return None

    dest.mkdir(parents=True, exist_ok=True)
    wrote_full_dir = _sparse_clone_skill_dir(git_url, skill_path, git_ref, dest)
    if not wrote_full_dir:
        rprint("[red]\u2717 Git skill clone failed.[/red]")
        return None
    rprint(f"[green]\u2713 Skill directory written:[/green] {esc(dest)}")
    if scope == "project" and not custom_dest:
        _symlink_for_harnesses(cwd or Path.cwd(), dest, skill_name)
    return dest


def _symlink_for_harnesses(cwd: Path, canonical: Path, skill_name: str) -> None:
    """Create .<agent>/skills/<name>/ symlinks for every harness config dir that exists."""
    for _harness, agent_dir in _HARNESS_SKILL_DIRS:
        agent_root = cwd / agent_dir
        if not agent_root.exists():
            continue
        skills_dir = agent_root / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        link = skills_dir / skill_name
        if link.exists() or link.is_symlink():
            continue
        link.symlink_to(canonical.resolve())
        rprint(f"[dim]  → symlinked {esc(link)} → {esc(canonical)}[/dim]")


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
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
):
    """Edit a draft, rejected, or pending skill submission.

    Updates fields on a skill that has not yet been approved. You can
    provide individual field options or load all updates from a JSON file.
    Acquires an edit lock to prevent concurrent modifications.

    Examples:
        observal registry skill edit my-skill --description "Better desc"
        observal registry skill edit abc123 --from-file updates.json
        observal registry skill edit @sk --git-url https://github.com/org/new-repo --output json
    """
    if from_file:
        try:
            with open(from_file) as f:
                updates = _json.load(f)
        except _json.JSONDecodeError as error:
            fail(
                ErrorCategory.VALIDATION,
                "The skill update file is not valid JSON.",
                operation="Edit skill",
                resource=from_file,
                remediation="Correct the JSON and retry.",
                detail=repr(error),
            )
        except FileNotFoundError as error:
            fail(
                ErrorCategory.NOT_FOUND,
                "The skill update file was not found.",
                operation="Edit skill",
                resource=from_file,
                remediation="Provide an existing update file and retry.",
                detail=repr(error),
            )
        if not isinstance(updates, dict):
            fail(
                ErrorCategory.VALIDATION,
                "The skill update file must contain a JSON object.",
                operation="Edit skill",
                resource=from_file,
                remediation="Replace the file contents with a JSON object and retry.",
            )
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
        fail(
            ErrorCategory.VALIDATION,
            "No skill changes were provided.",
            operation="Edit skill",
            resource=skill_id,
            remediation="Provide an update file or one or more field options.",
        )
    _validate_skill_fields(updates, "Edit skill")

    resolved = client.resolve_registry_reference("skill", skill_id)
    client.post(f"/api/v1/skills/{resolved}/start-edit")
    save_context = nullcontext() if output == "json" else spinner("Saving changes...")
    with save_context:
        result = client.put(f"/api/v1/skills/{resolved}/draft", updates)
    if output == "json":
        output_json(result)
    else:
        rprint(f"[green]✓ Updated {esc(result['name'])}[/green] (status: {esc(result.get('status', 'unknown'))})")
