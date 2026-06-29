# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Sandbox registry CLI commands."""

from __future__ import annotations

import json as _json

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.constants import VALID_HARNESSES, VALID_SANDBOX_NETWORK_POLICIES, VALID_SANDBOX_RUNTIME_TYPES
from observal_cli.prompts import select_one, text_input
from observal_cli.render import console, kv_panel, output_json, relative_time, spinner, status_badge

sandbox_app = typer.Typer(help="Sandbox registry commands")


def _print_sandbox_examples() -> None:
    examples = {
        "python-pytest": {
            "name": "python-pytest",
            "version": "1.0.0",
            "description": "Run Python tests in a reviewed Docker image",
            "owner": "your-team",
            "runtime_type": "docker",
            "image": "python:3.12-slim",
            "resource_limits": {"timeout": 60, "memory_mb": 512, "cpu_count": 1},
            "network_policy": "none",
            "entrypoint": "pytest",
            "runtime_config": {},
            "source_url": "https://github.com/docker-library/python",
            "source_ref": "master",
            "sandbox_path": "3.12/slim-bookworm",
        },
        "node-tests": {
            "name": "node-tests",
            "version": "1.0.0",
            "description": "Run Node test and build commands",
            "owner": "your-team",
            "runtime_type": "docker",
            "image": "node:22-alpine",
            "resource_limits": {"timeout": 120, "memory_mb": 1024, "cpu_count": 2},
            "network_policy": "none",
            "entrypoint": "npm test",
            "runtime_config": {},
            "source_url": "https://github.com/nodejs/docker-node",
            "source_ref": "main",
            "sandbox_path": "22/alpine3.22",
        },
        "go-tests": {
            "name": "go-tests",
            "version": "1.0.0",
            "description": "Run Go tests in an Alpine Go image",
            "owner": "your-team",
            "runtime_type": "docker",
            "image": "golang:1.24-alpine",
            "resource_limits": {"timeout": 180, "memory_mb": 1024, "cpu_count": 2},
            "network_policy": "none",
            "entrypoint": "go test ./...",
            "runtime_config": {},
            "source_url": "https://github.com/docker-library/golang",
            "source_ref": "master",
            "sandbox_path": "1.24/alpine3.21",
        },
    }
    output_json(examples)


def register_sandbox(app: typer.Typer):
    app.add_typer(sandbox_app, name="sandbox")


@sandbox_app.command(name="submit")
def sandbox_submit(
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Create from JSON file"),
    name: str | None = typer.Option(None, "--name", "-n", help="Sandbox name"),
    version: str | None = typer.Option(None, "--version", "-v", help="Version (default: 1.0.0)"),
    description: str | None = typer.Option(None, "--description", "-d", help="Short description"),
    runtime_type: str | None = typer.Option(None, "--runtime-type", "-r", help="Runtime type"),
    image: str | None = typer.Option(None, "--image", "-i", help="Container image"),
    resource_limits: str | None = typer.Option(None, "--resource-limits", help="Resource limits JSON"),
    runtime_config: str | None = typer.Option(None, "--runtime-config", help="Runtime-specific config JSON"),
    network_policy: str | None = typer.Option(None, "--network-policy", help="Network policy"),
    entrypoint: str | None = typer.Option(None, "--entrypoint", help="Default entrypoint"),
    supported_harnesses: list[str] | None = typer.Option(None, "--harness", help="Supported harness (repeatable)"),
    source_url: str | None = typer.Option(None, "--source-url", help="Source repository URL"),
    source_ref: str | None = typer.Option(None, "--source-ref", help="Source branch/tag"),
    sandbox_path: str | None = typer.Option(None, "--sandbox-path", help="Path in source repo"),
    draft: bool = typer.Option(False, "--draft", help="Save as draft instead of submitting for review"),
    submit_draft: str | None = typer.Option(None, "--submit", help="Submit a draft for review (sandbox ID)"),
    example: bool = typer.Option(False, "--example", help="Print example sandbox payloads and exit"),
):
    """Submit a new sandbox environment for review.

    Sandboxes are containerized execution environments for agent tasks.
    You can submit interactively, from a JSON file, or save as a draft
    first and submit later with --submit.

    Only submit sandboxes you created or are the point-of-contact for.

    Examples:
        observal registry sandbox submit
        observal registry sandbox submit --from-file sandbox.json
        observal registry sandbox submit --draft
        observal registry sandbox submit --submit abc123
    """
    if example:
        _print_sandbox_examples()
        return
    rprint("[dim]Note: Only submit components you created (private) or are the point-of-contact for (external).[/dim]")
    if draft and submit_draft:
        rprint(
            "[red]Cannot use --draft and --submit together.[/red] Use --draft to save a new draft, or --submit to submit an existing draft."
        )
        raise typer.Exit(code=1)
    if submit_draft:
        resolved = config.resolve_alias(submit_draft)
        with spinner("Submitting draft for review..."):
            result = client.post(f"/api/v1/sandboxes/{resolved}/submit")
        rprint(f"[green]✓ Draft submitted for review![/green] ID: [bold]{result['id']}[/bold]")
        return

    flag_mode = any(
        x is not None
        for x in (
            name,
            version,
            description,
            runtime_type,
            image,
            resource_limits,
            runtime_config,
            network_policy,
            entrypoint,
            supported_harnesses,
            source_url,
            source_ref,
            sandbox_path,
        )
    )
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
        if not payload.get("owner"):
            payload["owner"] = config.load().get("username", "")
    elif flag_mode:
        try:
            limits = _json.loads(resource_limits or "{}")
            runtime_cfg = _json.loads(runtime_config or "{}")
        except _json.JSONDecodeError as e:
            rprint(f"[red]Invalid JSON option:[/red] {e}")
            raise typer.Exit(1)
        payload = {
            "name": name,
            "version": version or "1.0.0",
            "description": description,
            "owner": config.load().get("username", ""),
            "runtime_type": runtime_type,
            "image": image,
            "resource_limits": limits,
            "runtime_config": runtime_cfg,
            "network_policy": network_policy or "none",
            "supported_harnesses": supported_harnesses or [],
        }
        if entrypoint:
            payload["entrypoint"] = entrypoint
        if source_url:
            payload["source_url"] = source_url
        if source_ref:
            payload["source_ref"] = source_ref
        if sandbox_path:
            payload["sandbox_path"] = sandbox_path
    else:
        payload = {
            "name": text_input("Sandbox name"),
            "version": text_input("Version", default="1.0.0"),
            "description": text_input("Description"),
            "owner": config.load().get("username", ""),
            "runtime_type": select_one("Runtime type", VALID_SANDBOX_RUNTIME_TYPES),
            "image": text_input("Image"),
            "resource_limits": _json.loads(text_input("Resource limits (JSON)")),
            "runtime_config": _json.loads(text_input("Runtime config (JSON)", default="{}")),
        }
    if flag_mode:
        if not (
            payload.get("name") and payload.get("description") and payload.get("runtime_type") and payload.get("image")
        ):
            rprint("[red]Error:[/red] --name, --description, --runtime-type, and --image are required")
            raise typer.Exit(1)
        if payload.get("runtime_type") not in VALID_SANDBOX_RUNTIME_TYPES:
            rprint(f"[red]Error:[/red] Invalid runtime type: {payload.get('runtime_type')}")
            raise typer.Exit(1)
        if payload.get("network_policy") not in VALID_SANDBOX_NETWORK_POLICIES:
            rprint(f"[red]Error:[/red] Invalid network policy: {payload.get('network_policy')}")
            raise typer.Exit(1)
        bad_harnesses = [h for h in payload.get("supported_harnesses", []) if h not in VALID_HARNESSES]
        if bad_harnesses:
            rprint(f"[red]Error:[/red] Invalid harness: {bad_harnesses[0]}")
            raise typer.Exit(1)

    if draft:
        with spinner("Saving draft..."):
            result = client.post("/api/v1/sandboxes/draft", payload)
        rprint(f"[green]✓ Draft saved![/green] ID: [bold]{result['id']}[/bold]")
    else:
        with spinner("Submitting sandbox..."):
            result = client.post("/api/v1/sandboxes/submit", payload)
        rprint(f"[green]✓ Sandbox submitted![/green] ID: [bold]{result['id']}[/bold]")


@sandbox_app.command(name="list")
def sandbox_list(
    runtime: str | None = typer.Option(None, "--runtime", "-r"),
    search: str | None = typer.Option(None, "--search", "-s"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List approved sandboxes in the registry.

    Shows only sandboxes with approved status. Use --runtime or --search
    to filter results. Row numbers from the output can be used as references
    in subsequent commands.

    Examples:
        observal registry sandbox list
        observal registry sandbox list --runtime docker
        observal registry sandbox list --search "node" --output json
    """
    params = {}
    if runtime:
        params["runtime"] = runtime
    if search:
        params["search"] = search
    with spinner("Fetching sandboxes..."):
        data = client.get("/api/v1/sandboxes", params=params)
    if not data:
        rprint("[dim]No sandboxes found.[/dim]")
        return
    config.save_last_results(data)
    if output == "json":
        output_json(data)
        return
    if output == "plain":
        for item in data:
            rprint(f"{item['id']}  {item['name']}  v{item.get('version', '?')}")
        return
    table = Table(title=f"Sandboxes ({len(data)})", show_lines=False, padding=(0, 1))
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


@sandbox_app.command(name="show")
def sandbox_show(
    sandbox_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show detailed information about a sandbox.

    Displays metadata including runtime type, container image, resource
    limits, status, and timestamps. Accepts a UUID, name, row number
    from a previous list, or @alias.

    Examples:
        observal registry sandbox show my-sandbox
        observal registry sandbox show 1
        observal registry sandbox show @dev-env --output json
    """
    resolved = config.resolve_alias(sandbox_id)
    with spinner():
        item = client.get(f"/api/v1/sandboxes/{resolved}")
    if output == "json":
        output_json(item)
        return
    console.print(
        kv_panel(
            f"{item['name']} v{item.get('version', '?')}",
            [
                ("Status", status_badge(item.get("status", ""))),
                ("Runtime", item.get("runtime_type", "N/A")),
                ("Image", item.get("image", "N/A")),
                ("Owner", item.get("owner", "N/A")),
                ("Description", item.get("description", "")),
                ("Created", relative_time(item.get("created_at"))),
                ("ID", f"[dim]{item['id']}[/dim]"),
            ],
            border_style="red",
        )
    )


@sandbox_app.command(name="edit")
def sandbox_edit(
    sandbox_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Load updates from JSON file"),
    name: str | None = typer.Option(None, "--name", "-n", help="New listing name"),
    description: str | None = typer.Option(None, "--description", "-d", help="New description"),
    version: str | None = typer.Option(None, "--version", "-v", help="New version string"),
    runtime_type: str | None = typer.Option(None, "--runtime-type", "-r", help="New runtime type"),
    image: str | None = typer.Option(None, "--image", "-i", help="New container image"),
    resource_limits: str | None = typer.Option(None, "--resource-limits", help="Resource limits JSON"),
    runtime_config: str | None = typer.Option(None, "--runtime-config", help="Runtime config JSON"),
    network_policy: str | None = typer.Option(None, "--network-policy", help="New network policy"),
    entrypoint: str | None = typer.Option(None, "--entrypoint", help="New entrypoint"),
):
    """Edit a draft, rejected, or pending sandbox submission.

    Updates fields on a sandbox that has not yet been approved. You can
    provide individual field options or load all updates from a JSON file.
    Acquires an edit lock to prevent concurrent modifications.

    Examples:
        observal registry sandbox edit my-sandbox --image node:20-alpine
        observal registry sandbox edit abc123 --from-file updates.json
        observal registry sandbox edit @env --runtime-type docker --version 2.0.0
    """
    resolved = config.resolve_alias(sandbox_id)
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
        if runtime_type is not None:
            updates["runtime_type"] = runtime_type
        if image is not None:
            updates["image"] = image
        if resource_limits is not None:
            updates["resource_limits"] = _json.loads(resource_limits)
        if runtime_config is not None:
            updates["runtime_config"] = _json.loads(runtime_config)
        if network_policy is not None:
            updates["network_policy"] = network_policy
        if entrypoint is not None:
            updates["entrypoint"] = entrypoint

    if not updates:
        rprint("[yellow]No changes specified.[/yellow] Use --from-file or field options (--name, --description, etc.)")
        raise typer.Exit(code=1)

    try:
        client.post(f"/api/v1/sandboxes/{resolved}/start-edit")
    except Exception as exc:
        if "409" in str(exc) or "currently being edited" in str(exc):
            rprint(f"[red]✗ Cannot edit:[/red] {exc}")
            raise typer.Exit(code=1)
    try:
        with spinner("Saving changes..."):
            result = client.put(f"/api/v1/sandboxes/{resolved}/draft", updates)
        rprint(f"[green]✓ Updated {result['name']}[/green] (status: {result.get('status', 'unknown')})")
    except Exception as exc:
        try:
            client.post(f"/api/v1/sandboxes/{resolved}/cancel-edit")
        except Exception:
            pass
        rprint(f"[red]Failed to update:[/red] {exc}")
        raise typer.Exit(code=1)
