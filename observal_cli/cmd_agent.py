"""Agent CLI commands."""

from __future__ import annotations

import json as _json
import re
from pathlib import Path

import typer
import yaml
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from observal_cli import client, config
from observal_cli.constants import AGENT_NAME_REGEX, VALID_IDES
from observal_cli.prompts import fuzzy_select, select_many, select_one
from observal_cli.render import (
    console,
    ide_tags,
    kv_panel,
    output_json,
    relative_time,
    spinner,
    status_badge,
)

# ── Agent authoring constants ──────────────────────────────
YAML_FILE = "observal-agent.yaml"
VALID_COMPONENT_TYPES = {"mcp", "skill", "hook", "prompt", "sandbox"}

# Common model choices for the interactive wizard
_MODEL_CHOICES = [
    "claude-sonnet-4",
    "claude-opus-4",
    "claude-haiku-4-5",
    "gemini-2.5-pro",
    "gpt-4o",
    "gpt-4.1",
]


def _slugify(raw: str) -> str:
    """Convert a raw name to a valid agent slug."""
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


def _validate_name(name: str) -> str | None:
    """Return error message if name is invalid, else None."""
    if not name:
        return "Agent name is required."
    if len(name) > 64:
        return "Agent name must be at most 64 characters."
    if not AGENT_NAME_REGEX.match(name):
        return "Must start with a letter/digit and contain only lowercase letters, digits, hyphens, underscores."
    return None


def _fetch_registry_items(component_type: str) -> list[dict]:
    """Fetch approved items from a registry endpoint. Returns [] on failure."""
    plural = {"mcp": "mcps", "skill": "skills", "hook": "hooks", "prompt": "prompts", "sandbox": "sandboxes"}
    try:
        return client.get(f"/api/v1/{plural[component_type]}")
    except (Exception, SystemExit):
        return []


# ── Agent authoring helpers ────────────────────────────────
def _load_agent_yaml(directory: Path) -> dict:
    """Load and return the agent YAML from *directory*. Exits if missing."""
    path = directory / YAML_FILE
    if not path.exists():
        rprint(f"[red]Error:[/red] {YAML_FILE} not found in {directory}")
        raise typer.Exit(code=1)
    with open(path) as f:
        return yaml.safe_load(f)


def _save_agent_yaml(directory: Path, data: dict) -> None:
    """Write *data* as YAML to *directory*/observal-agent.yaml."""
    path = directory / YAML_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


agent_app = typer.Typer(help="Agent registry commands")


@agent_app.command(name="create")
def agent_create(
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Create from JSON file"),
):
    """Create a new agent (interactive wizard or from file)."""
    if from_file:
        import json

        with open(from_file) as f:
            payload = json.load(f)
        with spinner("Creating agent..."):
            result = client.post("/api/v1/agents", payload)
        status = result.get("status", "pending")
        rprint(f"[green]✓ Agent submitted for review![/green] ID: [bold]{result['id']}[/bold]")
        rprint(f"[yellow]Status: {status} — an admin must approve it before it becomes visible.[/yellow]")
        return

    rprint("\n[bold cyan]Agent Builder[/bold cyan]\n")

    # ── Phase 1: Basics ─────────────────────────────────────
    rprint("[bold]1. Basics[/bold]")
    raw_name = typer.prompt("  Agent name")
    name = _slugify(raw_name)
    if name != raw_name:
        rprint(f"  [dim]→ Slugified to:[/dim] [bold]{name}[/bold]")
    err = _validate_name(name)
    if err:
        rprint(f"  [red]Error:[/red] {err}")
        raise typer.Exit(1)

    description = typer.prompt("  Description")
    version = typer.prompt("  Version", default="1.0.0")
    model_name = select_one("  Model", _MODEL_CHOICES, default="claude-sonnet-4")

    # ── Phase 2: Components ──────────────────────────────────
    rprint("\n[bold]2. Components[/bold]")
    components: list[dict] = []

    with spinner("Fetching registry..."):
        registry_data: dict[str, list[dict]] = {}
        for ctype in ("mcp", "skill", "hook", "prompt", "sandbox"):
            registry_data[ctype] = _fetch_registry_items(ctype)

    for ctype in ("mcp", "skill", "hook", "prompt", "sandbox"):
        items = registry_data[ctype]
        if not items:
            rprint(f"  [dim]No {ctype}s available — skipping.[/dim]")
            continue

        choices = [f"{item['name']}  [dim]({str(item['id'])[:8]})[/dim]" for item in items]
        selected = select_many(f"  Select {ctype}s", choices, defaults=[])

        for sel in selected:
            # Match back to item by prefix (name part before the dim ID)
            sel_name = sel.split("  [dim]")[0].strip()
            match = next((item for item in items if item["name"] == sel_name), None)
            if match:
                components.append({"component_type": ctype, "component_id": str(match["id"])})

    # ── Phase 3: IDEs ────────────────────────────────────────
    rprint("\n[bold]3. Supported IDEs[/bold]")
    supported_ides = select_many("  IDEs", list(VALID_IDES), defaults=list(VALID_IDES))

    # ── Phase 4: Goal Template ───────────────────────────────
    rprint("\n[bold]4. Goal Template[/bold]")
    goal_desc = typer.prompt("  Goal description", default=description)
    sections = []
    while True:
        sec_name = typer.prompt("  Section name (or 'done' to finish)")
        if sec_name.lower() == "done":
            break
        sec_desc = typer.prompt(f"    Description for '{sec_name}'", default="")
        sections.append({"name": sec_name, "description": sec_desc})

    if not sections:
        sections = [{"name": "default", "description": goal_desc}]
        rprint("  [dim]Using default section.[/dim]")

    # ── Phase 5: Optional Details ────────────────────────────
    rprint("\n[bold]5. Optional Details[/bold]")
    # Try to get owner from whoami
    default_owner = ""
    try:
        whoami = client.get("/api/v1/auth/whoami")
        default_owner = whoami.get("name") or whoami.get("email", "")
    except (Exception, SystemExit):
        pass
    owner = typer.prompt("  Owner / Team", default=default_owner or "")
    prompt_text = typer.prompt("  System prompt (optional)", default="")
    max_tokens = typer.prompt("  Max tokens", default="4096")
    temperature = typer.prompt("  Temperature", default="0.2")
    model_cfg = {"max_tokens": int(max_tokens), "temperature": float(temperature)}

    # ── Phase 6: Review & Confirm ────────────────────────────
    component_summary = (
        ", ".join(
            f"{sum(1 for c in components if c['component_type'] == t)} {t}s"
            for t in ("mcp", "skill", "hook", "prompt", "sandbox")
            if any(c["component_type"] == t for c in components)
        )
        or "none"
    )

    review = (
        f"[bold]{name}[/bold] v{version}  |  Model: [cyan]{model_name}[/cyan]\n"
        f"Components: {component_summary}\n"
        f"IDEs: {', '.join(supported_ides)}\n"
        f"Goal: {len(sections)} section(s)"
    )
    console.print(Panel(review, title="Review", border_style="green"))

    if not typer.confirm("\nSubmit this agent for review?", default=True):
        rprint("[yellow]Aborted.[/yellow]")
        raise typer.Exit(0)

    with spinner("Creating agent..."):
        result = client.post(
            "/api/v1/agents",
            {
                "name": name,
                "version": version,
                "description": description,
                "owner": owner,
                "prompt": prompt_text,
                "model_name": model_name,
                "model_config_json": model_cfg,
                "supported_ides": supported_ides,
                "components": components,
                "goal_template": {"description": goal_desc, "sections": sections},
            },
        )
    status = result.get("status", "pending")
    rprint(f"\n[green]✓ Agent submitted for review![/green] ID: [bold]{result['id']}[/bold]")
    rprint(f"[yellow]Status: {status} — an admin must approve it before it becomes visible.[/yellow]")


@agent_app.command(name="bulk-create")
def agent_bulk_create(
    file_path: str = typer.Option(..., "--from-file", help="JSON file with agent definitions"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without creating"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Bulk-create agents from a JSON file."""
    import json

    path = Path(file_path)
    if not path.exists():
        rprint(f"[red]Error:[/red] File not found: {file_path}")
        raise typer.Exit(code=1)

    try:
        with open(path) as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        rprint(f"[red]Error:[/red] Invalid JSON: {exc}")
        raise typer.Exit(code=1)

    # Accept {"agents": [...]} or bare [...]
    if isinstance(raw, list):
        agents = raw
    elif isinstance(raw, dict) and "agents" in raw:
        agents = raw["agents"]
    else:
        rprint("[red]Error:[/red] JSON must be {\"agents\": [...]} or a bare array.")
        raise typer.Exit(code=1)

    if not agents:
        rprint("[yellow]No agents found in file.[/yellow]")
        raise typer.Exit(code=1)

    # ── Preview table ────────────────────────────────────────
    preview = Table(title=f"Agents to create ({len(agents)})", show_lines=False, padding=(0, 1))
    preview.add_column("#", style="dim", width=3)
    preview.add_column("Name", style="bold cyan", no_wrap=True)
    preview.add_column("Version", style="green")
    preview.add_column("Components")
    preview.add_column("Model")
    for i, ag in enumerate(agents, 1):
        comp_count = str(len(ag.get("components", [])))
        preview.add_row(
            str(i),
            ag.get("name", "unnamed"),
            ag.get("version", "1.0.0"),
            comp_count,
            ag.get("model_name", "claude-sonnet-4"),
        )
    console.print(preview)

    # ── Dry-run mode ─────────────────────────────────────────
    if dry_run:
        with spinner("Running dry-run..."):
            result = client.post("/api/v1/bulk/agents", {"agents": agents, "dry_run": True})

        results_table = Table(title="Dry-run results", show_lines=False, padding=(0, 1))
        results_table.add_column("#", style="dim", width=3)
        results_table.add_column("Name", style="bold cyan", no_wrap=True)
        results_table.add_column("Status")
        results_table.add_column("Error", style="red")
        for i, item in enumerate(result.get("results", []), 1):
            status = item.get("status", "")
            badge = "[green]created[/green]" if status == "created" else (
                "[yellow]skipped[/yellow]" if status == "skipped" else f"[red]{status}[/red]"
            )
            results_table.add_row(str(i), item.get("name", ""), badge, item.get("error", "") or "")
        console.print(results_table)

        rprint(
            f"\n[bold]Summary:[/bold] {result.get('created', 0)} would be created, "
            f"{result.get('skipped', 0)} skipped, {result.get('errors', 0)} errors"
        )
        return

    # ── Confirmation ─────────────────────────────────────────
    if not yes:
        if not typer.confirm(f"\nCreate {len(agents)} agents?", default=False):
            rprint("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)

    # ── Create ───────────────────────────────────────────────
    with spinner("Creating agents..."):
        result = client.post("/api/v1/bulk/agents", {"agents": agents, "dry_run": False})

    results_table = Table(title="Bulk create results", show_lines=False, padding=(0, 1))
    results_table.add_column("#", style="dim", width=3)
    results_table.add_column("Name", style="bold cyan", no_wrap=True)
    results_table.add_column("Status")
    results_table.add_column("Agent ID", style="dim")
    results_table.add_column("Error", style="red")
    for i, item in enumerate(result.get("results", []), 1):
        status = item.get("status", "")
        badge = "[green]created[/green]" if status == "created" else (
            "[yellow]skipped[/yellow]" if status == "skipped" else f"[red]{status}[/red]"
        )
        agent_id = str(item["agent_id"])[:8] + "…" if item.get("agent_id") else ""
        results_table.add_row(str(i), item.get("name", ""), badge, agent_id, item.get("error", "") or "")
    console.print(results_table)

    rprint(
        f"\n[green]✓ Bulk create complete![/green] "
        f"{result.get('created', 0)} created, {result.get('skipped', 0)} skipped, "
        f"{result.get('errors', 0)} errors"
    )


@agent_app.command(name="list")
def agent_list(
    search: str | None = typer.Option(None, "--search", "-s"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Interactive search mode"),
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=200, help="Page size (1-200)"),
    page: int = typer.Option(1, "--page", "-p", min=1, help="Page number (1-indexed)"),
    show_id: bool = typer.Option(False, "--id", help="Include the agent ID column"),
    full_id: bool = typer.Option(False, "--full-id", help="Show full UUID (implies --id)"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List active agents (paginated)."""
    params: dict = {"limit": limit, "offset": (page - 1) * limit}
    if search:
        params["search"] = search

    with spinner("Fetching agents..."):
        data, headers = client.get_with_headers("/api/v1/agents", params=params)

    if interactive and data:

        def _display(item: dict) -> str:
            email = item.get("created_by_email", "")
            suffix = f"  by {email}" if email else ""
            return f"{item['name']}  v{item.get('version', '?')}  {item.get('model_name', '')}{suffix}"

        selected = fuzzy_select(data, _display, label="Select agent")
        if selected:
            agent_show(selected["id"])
        return

    total = int(headers.get("x-total-count", str(len(data))))
    total_pages = max(1, (total + limit - 1) // limit)

    if not data:
        if total == 0:
            rprint("[dim]No agents found.[/dim]")
        else:
            rprint(f"[yellow]Page {page} is empty. Total agents: {total} (last page: {total_pages})[/yellow]")
        return

    # Cache IDs for numeric shorthand
    config.save_last_results(data)

    if output == "json":
        output_json(data)
        return

    if output == "plain":
        for item in data:
            rprint(f"{item['name']}  v{item.get('version', '?')}  {item.get('model_name', '')}")
        return

    include_id = show_id or full_id
    table = Table(
        title=f"Agents (page {page} of {total_pages} · {len(data)} of {total})",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Version", style="green")
    table.add_column("Model")
    table.add_column("Created By", style="dim")
    if include_id:
        table.add_column("ID", style="dim", no_wrap=full_id)
    for i, item in enumerate(data, 1):
        creator = item.get("created_by_username") or item.get("created_by_email", "")
        row = [str(i), item["name"], item.get("version", ""), item.get("model_name", ""), creator]
        if include_id:
            row.append(str(item["id"]) if full_id else str(item["id"])[:8] + "…")
        table.add_row(*row)
    console.print(table)

    # Pagination footer
    if total_pages > 1:
        if page < total_pages:
            rprint(
                f"[dim]Next:[/dim] [bold]observal agent list --page {page + 1}[/bold]"
                + (f" --limit {limit}" if limit != 50 else "")
            )
        else:
            rprint("[dim]End of results.[/dim]")


@agent_app.command(name="show")
def agent_show(
    agent_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show full agent details."""
    resolved = config.resolve_alias(agent_id)
    with spinner():
        item = client.get(f"/api/v1/agents/{resolved}")

    if output == "json":
        output_json(item)
        return

    console.print(
        kv_panel(
            f"{item['name']} v{item.get('version', '?')}",
            [
                ("Status", status_badge(item.get("status", ""))),
                ("Model", f"[bold]{item.get('model_name', 'N/A')}[/bold]"),
                ("Owner", item.get("owner", "N/A")),
                ("Created By", item.get("created_by_username") or item.get("created_by_email", "")),
                ("Description", item.get("description", "")),
                ("IDEs", ide_tags(item.get("supported_ides", []))),
                ("Created", relative_time(item.get("created_at"))),
                ("ID", f"[dim]{item['id']}[/dim]"),
            ],
            border_style="magenta",
        )
    )

    # MCP links
    if item.get("mcp_links"):
        rprint("\n[bold]Linked MCP Servers:[/bold]")
        for link in item["mcp_links"]:
            rprint(f"  [cyan]•[/cyan] {link.get('mcp_name', '')} [dim]({link.get('mcp_listing_id', '')})[/dim]")

    # Goal template as tree
    if item.get("goal_template"):
        gt = item["goal_template"]
        tree = Tree(f"[bold]Goal:[/bold] {gt.get('description', '')}")
        for sec in gt.get("sections", []):
            label = sec["name"]
            if sec.get("grounding_required"):
                label += " [yellow](grounding required)[/yellow]"
            node = tree.add(label)
            if sec.get("description"):
                node.add(f"[dim]{sec['description']}[/dim]")
        console.print(tree)


@agent_app.command(name="install")
def agent_install(
    agent_id: str = typer.Argument(..., help="Agent ID, name, row number, or @alias"),
    ide: str = typer.Option(..., "--ide", "-i", help="Target IDE"),
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON only"),
):
    """Get install config for an agent."""
    resolved = config.resolve_alias(agent_id)
    with spinner(f"Generating {ide} config..."):
        result = client.post(f"/api/v1/agents/{resolved}/install", {"ide": ide})

    snippet = result.get("config_snippet", {})
    if raw:
        print(_json.dumps(snippet, indent=2))
        return

    rprint(f"\n[bold]Config for {ide}:[/bold]\n")

    # Kiro agent file: single JSON to drop in
    agent_file = snippet.get("agent_file")
    if agent_file:
        rprint(f"[bold]Save to:[/bold] {agent_file['path']}")
        rprint()
        console.print_json(_json.dumps(agent_file["content"], indent=2))
        rprint(
            f"\n[dim]Or pipe:[/dim] observal agent install {agent_id} --ide {ide} --raw | jq .agent_file.content > {agent_file['path']}"
        )
        return

    # Rules file
    rules = snippet.get("rules_file")
    if rules:
        rprint(f"[bold]Rules file:[/bold] {rules.get('path', '')}")
        content = rules.get("content", "")
        rprint(f"[dim]{content[:200]}{'...' if len(content) > 200 else ''}[/dim]\n")

    # MCP config
    mcp_cfg = snippet.get("mcp_config")
    if mcp_cfg:
        path = mcp_cfg.get("path") if isinstance(mcp_cfg, dict) and "path" in mcp_cfg else None
        content = mcp_cfg.get("content", mcp_cfg) if isinstance(mcp_cfg, dict) and "content" in mcp_cfg else mcp_cfg
        if path:
            rprint(f"[bold]MCP config:[/bold] {path}")
        else:
            rprint("[bold]MCP config:[/bold]")
        console.print_json(_json.dumps(content, indent=2))
        return

    # Fallback
    console.print_json(_json.dumps(snippet, indent=2))


@agent_app.command(name="delete")
def agent_delete(
    agent_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Archive an agent (soft delete)."""
    resolved = config.resolve_alias(agent_id)
    if not yes:
        with spinner():
            item = client.get(f"/api/v1/agents/{resolved}")
        if not typer.confirm(f"Archive [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    with spinner("Archiving..."):
        client.patch(f"/api/v1/agents/{resolved}/archive")
    rprint("[green]✓ Agent archived[/green]")


# ═══════════════════════════════════════════════════════════════
# Agent authoring commands (local YAML workflow)
# ═══════════════════════════════════════════════════════════════


@agent_app.command(name="init")
def agent_init(
    directory: str = typer.Option(".", "--dir", "-d", help="Directory to scaffold in"),
    beta: bool = typer.Option(False, "--beta", help="Start at version 0.1.0 (beta)"),
):
    """Scaffold an observal-agent.yaml definition file."""
    dir_path = Path(directory)
    yaml_path = dir_path / YAML_FILE

    if yaml_path.exists() and not typer.confirm(f"{YAML_FILE} already exists in {dir_path}. Overwrite?"):
        rprint("[yellow]Aborted.[/yellow]")
        raise typer.Exit(code=1)

    raw_name = typer.prompt("Agent name")
    name = _slugify(raw_name)
    if name != raw_name:
        rprint(f"  [dim]→ Slugified to:[/dim] [bold]{name}[/bold]")
    err = _validate_name(name)
    if err:
        rprint(f"[red]Error:[/red] {err}")
        raise typer.Exit(1)

    default_version = "0.1.0" if beta else "1.0.0"
    version = typer.prompt("Version", default=default_version)
    description = typer.prompt("Description")
    owner = typer.prompt("Owner / Team")
    model_name = typer.prompt("Model name", default="claude-sonnet-4")
    prompt_text = typer.prompt("System prompt")

    data = {
        "name": name,
        "version": version,
        "description": description,
        "owner": owner,
        "model_name": model_name,
        "prompt": prompt_text,
        "supported_ides": list(VALID_IDES),
        "components": [],
        "goal_template": {
            "description": f"Goals for {name}",
            "sections": [
                {"name": "default", "description": "Default goal section"},
            ],
        },
    }

    _save_agent_yaml(dir_path, data)
    rprint(f"[green]✓ Created {yaml_path}[/green]")


@agent_app.command(name="add")
def agent_add(
    component_type: str = typer.Argument(..., help="Component type: mcp, skill, hook, prompt, sandbox"),
    component_id: str = typer.Argument(..., help="Component ID (UUID)"),
    directory: str = typer.Option(".", "--dir", "-d", help="Directory containing observal-agent.yaml"),
):
    """Add a component reference to observal-agent.yaml."""
    if component_type not in VALID_COMPONENT_TYPES:
        rprint(
            f"[red]Error:[/red] Invalid component type '{component_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_COMPONENT_TYPES))}"
        )
        raise typer.Exit(code=1)

    dir_path = Path(directory)
    data = _load_agent_yaml(dir_path)

    components = data.get("components", [])
    for comp in components:
        if comp.get("component_type") == component_type and comp.get("component_id") == component_id:
            rprint(f"[yellow]Component {component_type}:{component_id} already exists.[/yellow]")
            raise typer.Exit(code=1)

    components.append({"component_type": component_type, "component_id": component_id})
    data["components"] = components
    _save_agent_yaml(dir_path, data)
    rprint(f"[green]✓ Added {component_type}:{component_id}[/green]")


@agent_app.command(name="build")
def agent_build(
    directory: str = typer.Option(".", "--dir", "-d", help="Directory containing observal-agent.yaml"),
):
    """Validate agent definition against the server (dry-run)."""
    dir_path = Path(directory)
    data = _load_agent_yaml(dir_path)

    rprint(f"[bold]Agent:[/bold] {data.get('name', 'unnamed')} v{data.get('version', '?')}")
    rprint(f"[bold]Model:[/bold] {data.get('model_name', 'N/A')}")
    rprint()

    components = data.get("components", [])
    if not components:
        rprint("[dim]No components to validate.[/dim]")
        return

    table = Table(title="Component Validation", show_lines=False)
    table.add_column("Type", style="bold")
    table.add_column("ID", style="dim")
    table.add_column("Status")

    errors: list[str] = []
    for comp in components:
        ctype = comp["component_type"]
        cid = comp["component_id"]
        # API convention: plural resource name
        plural = {"mcp": "mcps", "skill": "skills", "hook": "hooks", "prompt": "prompts", "sandbox": "sandboxes"}
        endpoint = f"/api/v1/{plural[ctype]}/{cid}"
        try:
            with spinner(f"Checking {ctype} {cid[:8]}..."):
                client.get(endpoint)
            table.add_row(ctype, cid, "[green]✓ valid[/green]")
        except (Exception, SystemExit):
            table.add_row(ctype, cid, "[red]✗ not found[/red]")
            errors.append(f"{ctype}:{cid}")

    console.print(table)

    if errors:
        rprint(f"\n[red]{len(errors)} component(s) failed validation:[/red]")
        for e in errors:
            rprint(f"  [red]•[/red] {e}")
        raise typer.Exit(code=1)
    else:
        rprint("\n[green]✓ All components valid.[/green]")


@agent_app.command(name="publish")
def agent_publish(
    directory: str = typer.Option(".", "--dir", "-d", help="Directory containing observal-agent.yaml"),
    update: bool = typer.Option(False, "--update", "-u", help="Update existing agent instead of creating"),
    draft: bool = typer.Option(False, "--draft", help="Save as draft instead of submitting for review"),
    submit: str | None = typer.Option(None, "--submit", help="Submit a draft agent for review (agent ID)"),
):
    """Publish the agent definition to the server."""
    if submit:
        resolved = config.resolve_alias(submit)
        with spinner("Submitting draft for review..."):
            result = client.post(f"/api/v1/agents/{resolved}/submit")
        rprint(f"[green]✓ Draft submitted for review![/green] ID: [bold]{result['id']}[/bold]")
        return

    dir_path = Path(directory)
    data = _load_agent_yaml(dir_path)

    payload = {
        "name": data["name"],
        "version": data.get("version", "1.0.0"),
        "description": data.get("description", ""),
        "owner": data.get("owner", ""),
        "model_name": data.get("model_name", "claude-sonnet-4"),
        "prompt": data.get("prompt", ""),
        "supported_ides": data.get("supported_ides", []),
        "components": data.get("components", []),
        "goal_template": data.get("goal_template", {}),
    }

    if draft:
        with spinner("Saving draft..."):
            result = client.post("/api/v1/agents/draft", payload)
        rprint(f"[green]✓ Draft saved![/green] ID: [bold]{result['id']}[/bold]")
        return

    if update:
        # Find existing agent by name
        with spinner("Looking up existing agent..."):
            results = client.get("/api/v1/agents", params={"search": data["name"]})
        match = next((a for a in results if a["name"] == data["name"]), None)
        if not match:
            rprint(f"[red]Error:[/red] No existing agent found with name '{data['name']}'")
            raise typer.Exit(code=1)
        agent_id = match["id"]

        # Version bump selection (interactive only)
        import sys

        if sys.stdin.isatty():
            current_version = match.get("version", "1.0.0")
            try:
                suggestions = client.get(f"/api/v1/agents/{agent_id}/version-suggestions")
                sug = suggestions.get("suggestions", {})
                bump_choices = [
                    f"patch  {current_version} → {sug.get('patch', '?')}  (bug fix)",
                    f"minor  {current_version} → {sug.get('minor', '?')}  (improvement)",
                    f"major  {current_version} → {sug.get('major', '?')}  (revamp)",
                    "keep   (use version from YAML)",
                ]
                choice = select_one("Version bump type", bump_choices, default=bump_choices[0])
                bump_type = choice.split()[0]
                if bump_type != "keep":
                    payload["version_bump_type"] = bump_type
                    payload.pop("version", None)
            except (Exception, SystemExit):
                pass

        with spinner("Updating agent..."):
            result = client.put(f"/api/v1/agents/{agent_id}", payload)
        rprint(f"[green]✓ Agent updated![/green] ID: [bold]{result['id']}[/bold]  v{result.get('version', '?')}")
    else:
        with spinner("Submitting agent for review..."):
            result = client.post("/api/v1/agents", payload)
        status = result.get("status", "pending")
        rprint(f"[green]✓ Agent submitted for review![/green] ID: [bold]{result['id']}[/bold]")
        rprint(f"[yellow]Status: {status} — an admin must approve it before it becomes visible.[/yellow]")
