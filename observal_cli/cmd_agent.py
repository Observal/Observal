"""Agent CLI commands."""

from __future__ import annotations

import json as _json
from pathlib import Path

import typer
import yaml
from rich import print as rprint
from rich.table import Table
from rich.tree import Tree

from observal_cli import client, config
from observal_cli.constants import VALID_IDES
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
    """Create a new agent (interactive or from file)."""
    if from_file:
        import json

        with open(from_file) as f:
            payload = json.load(f)
        with spinner("Creating agent..."):
            result = client.post("/api/v1/agents", payload)
        rprint(f"[green]✓ Agent created![/green] ID: [bold]{result['id']}[/bold]")
        return

    name = typer.prompt("Agent name")
    version = typer.prompt("Version", default="1.0.0")
    description = typer.prompt("Description")
    owner = typer.prompt("Owner / Team")
    prompt_text = typer.prompt("System prompt")
    model_name = typer.prompt("Model name", default="claude-sonnet-4")

    max_tokens = typer.prompt("Max tokens", default="4096")
    temperature = typer.prompt("Temperature", default="0.2")
    model_cfg = {"max_tokens": int(max_tokens), "temperature": float(temperature)}

    ide_choices = list(VALID_IDES)
    rprint(f"[dim]IDEs: {', '.join(ide_choices)}[/dim]")
    ides_input = typer.prompt("Supported IDEs (comma-separated)", default=",".join(ide_choices))
    supported_ides = [i.strip() for i in ides_input.split(",") if i.strip()]

    # MCP server selection
    rprint()
    with spinner("Fetching MCP servers..."):
        try:
            mcps = client.get("/api/v1/mcps")
        except (Exception, SystemExit):
            mcps = []

    if mcps:
        table = Table(title="Available MCP Servers", show_lines=False)
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="bold")
        table.add_column("ID", style="dim")
        for i, m in enumerate(mcps, 1):
            table.add_row(str(i), m["name"], str(m["id"])[:12] + "…")
        console.print(table)
        rprint()
    else:
        rprint("[dim]No approved MCP servers available.[/dim]")

    mcp_input = typer.prompt("MCP server IDs (comma-separated, or empty)", default="")
    mcp_ids = [i.strip() for i in mcp_input.split(",") if i.strip()]

    # Goal template
    rprint("\n[bold]Goal Template[/bold]")
    goal_desc = typer.prompt("Goal description")
    sections = []
    while True:
        sec_name = typer.prompt("Section name (or 'done')")
        if sec_name.lower() == "done":
            break
        sec_desc = typer.prompt(f"  Description for '{sec_name}'", default="")
        grounding = typer.confirm("  Grounding required?", default=False)
        sections.append({"name": sec_name, "description": sec_desc, "grounding_required": grounding})

    if not sections:
        rprint("[red]At least one goal section is required.[/red]")
        raise typer.Exit(1)

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
                "mcp_server_ids": mcp_ids,
                "goal_template": {"description": goal_desc, "sections": sections},
            },
        )
    rprint(f"\n[green]✓ Agent created![/green] ID: [bold]{result['id']}[/bold]")


@agent_app.command(name="list")
def agent_list(
    search: str | None = typer.Option(None, "--search", "-s"),
    limit: int = typer.Option(50, "--limit", "-n"),
    full_id: bool = typer.Option(False, "--full-id", help="Show full UUID instead of short form"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List active agents."""
    params = {"search": search} if search else {}
    with spinner("Fetching agents..."):
        data = client.get("/api/v1/agents", params=params)

    if not data:
        rprint("[dim]No agents found.[/dim]")
        return

    data = data[:limit]

    # Cache IDs for numeric shorthand
    config.save_last_results(data)

    if output == "json":
        output_json(data)
        return

    if output == "plain":
        for item in data:
            rprint(
                f"{item['id']}  {item['name']}  v{item.get('version', '?')}  {item.get('model_name', '')}  {', '.join(item.get('supported_ides', []))}"
            )
        return

    table = Table(title=f"Agents ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Version", style="green")
    table.add_column("Model")
    table.add_column("Owner", style="dim")
    table.add_column("IDEs")
    table.add_column("ID", style="dim", no_wrap=full_id)
    for i, item in enumerate(data, 1):
        id_display = str(item["id"]) if full_id else str(item["id"])[:8] + "…"
        table.add_row(
            str(i),
            item["name"],
            item.get("version", ""),
            item.get("model_name", ""),
            item.get("owner", ""),
            ide_tags(item.get("supported_ides", [])),
            id_display,
        )
    console.print(table)


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
    """Delete an agent."""
    resolved = config.resolve_alias(agent_id)
    if not yes:
        with spinner():
            item = client.get(f"/api/v1/agents/{resolved}")
        if not typer.confirm(f"Delete [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    with spinner("Deleting..."):
        client.delete(f"/api/v1/agents/{resolved}")
    rprint(f"[green]✓ Deleted {resolved}[/green]")


# ═══════════════════════════════════════════════════════════════
# Agent authoring commands (local YAML workflow)
# ═══════════════════════════════════════════════════════════════


@agent_app.command(name="init")
def agent_init(
    directory: str = typer.Option(".", "--dir", "-d", help="Directory to scaffold in"),
):
    """Scaffold an observal-agent.yaml definition file."""
    dir_path = Path(directory)
    yaml_path = dir_path / YAML_FILE

    if yaml_path.exists() and not typer.confirm(f"{YAML_FILE} already exists in {dir_path}. Overwrite?"):
        rprint("[yellow]Aborted.[/yellow]")
        raise typer.Exit(code=1)

    name = typer.prompt("Agent name")
    version = typer.prompt("Version", default="1.0.0")
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
):
    """Publish the agent definition to the server."""
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

    if update:
        # Find existing agent by name
        with spinner("Looking up existing agent..."):
            results = client.get("/api/v1/agents", params={"search": data["name"]})
        match = next((a for a in results if a["name"] == data["name"]), None)
        if not match:
            rprint(f"[red]Error:[/red] No existing agent found with name '{data['name']}'")
            raise typer.Exit(code=1)
        agent_id = match["id"]
        with spinner("Updating agent..."):
            result = client.put(f"/api/v1/agents/{agent_id}", payload)
        rprint(f"[green]✓ Agent updated![/green] ID: [bold]{result['id']}[/bold]")
    else:
        with spinner("Creating agent..."):
            result = client.post("/api/v1/agents", payload)
        rprint(f"[green]✓ Agent created![/green] ID: [bold]{result['id']}[/bold]")
