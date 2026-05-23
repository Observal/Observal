# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-License-Identifier: AGPL-3.0-only

"""Review, telemetry, dashboard, feedback, admin, and trace CLI commands."""

from __future__ import annotations

import time

import httpx
import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.render import (
    console,
    kv_panel,
    output_json,
    relative_time,
    spinner,
    star_rating,
    status_badge,
)


def _require_enterprise():
    """Check that the server is running in enterprise mode. Exit with a clear message if not."""
    try:
        cfg = config.load()
        server_url = cfg.get("server_url", "").rstrip("/")
        if not server_url:
            return
        r = httpx.get(f"{server_url}/api/v1/config/public", timeout=5)
        if r.status_code == 200:
            pub = r.json()
            if pub.get("deployment_mode") != "enterprise":
                rprint("[yellow]This feature requires enterprise mode.[/yellow]")
                rprint("[dim]Set DEPLOYMENT_MODE=enterprise on the server to enable.[/dim]")
                raise typer.Exit(1)
    except (httpx.ConnectError, httpx.TimeoutException):
        pass
    except typer.Exit:
        raise
    except Exception as exc:
        rprint(f"[dim]Warning: could not verify enterprise mode: {exc}[/dim]")


# ═══════════════════════════════════════════════════════════
# ops_app: Observability / operational commands group
# ═══════════════════════════════════════════════════════════

ops_app = typer.Typer(
    name="ops",
    help="Observability and operational commands (traces, telemetry, dashboard, feedback)",
    no_args_is_help=True,
)


# ── Review ───────────────────────────────────────────────

review_app = typer.Typer(help="Admin review commands")


@review_app.command(name="list")
def review_list(
    type_filter: str = typer.Option(None, "--type", "-t", help="Filter by type (mcp, skill, hook, prompt, sandbox)"),
    tab: str = typer.Option(None, "--tab", help="Filter tab (agents, components)"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """List pending submissions awaiting admin review.

    Shows all components and agents that have been submitted but not yet
    approved or rejected. Use --type to filter by component type, or --tab
    to separate agents from components.

    Row numbers from the output can be used as shorthand in other review
    commands (show, approve, reject).

    Examples:

        observal admin review list

        observal admin review list --type mcp

        observal admin review list --tab agents --output json
    """
    params = {}
    if type_filter:
        params["type"] = type_filter
    if tab:
        params["tab"] = tab
    with spinner("Fetching reviews..."):
        data = client.get("/api/v1/review", params=params or None)
    if data:
        config.save_last_results(data)
    if output == "json":
        output_json(data)
        return
    if not data:
        rprint("[dim]No pending reviews.[/dim]")
        return
    table = Table(title=f"Pending Reviews ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Type", style="cyan", width=8)
    table.add_column("Name", style="bold")
    table.add_column("Version", style="dim")
    table.add_column("Submitted By")
    table.add_column("Submitted", style="dim")
    table.add_column("ID", style="dim", no_wrap=True, max_width=12)
    for i, item in enumerate(data, 1):
        table.add_row(
            str(i),
            item.get("type", item.get("listing_type", "")),
            item.get("name", ""),
            item.get("version", ""),
            item.get("submitted_by", ""),
            relative_time(item.get("created_at") or item.get("submitted_at")),
            str(item["id"])[:12],
        )
    console.print(table)


@review_app.command(name="show")
def review_show(
    review_id: str = typer.Argument(..., help="Name, row #, @alias, or UUID"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show review details for a component or agent.

    Displays metadata, validation results, and status for a pending
    submission. Accepts a row number from `review list`, a name,
    an @alias, or a UUID.

    Examples:

        observal admin review show 1

        observal admin review show my-mcp-server

        observal admin review show @my-alias --output json
    """
    resolved = config.resolve_alias(review_id)
    with spinner():
        item = client.get(f"/api/v1/review/{resolved}")
    if output == "json":
        output_json(item)
        return
    fields = [
        ("Type", item.get("type", "N/A")),
        ("Status", status_badge(item.get("status", ""))),
        ("Version", item.get("version", "N/A")),
        ("Owner", item.get("owner", "N/A")),
        ("Submitted By", item.get("submitted_by", "N/A")),
        ("Created", relative_time(item.get("created_at"))),
        ("Git URL", item.get("git_url", "N/A")),
        ("Description", item.get("description", "") or "[dim]none[/dim]"),
        ("ID", f"[dim]{item['id']}[/dim]"),
    ]
    if item.get("rejection_reason"):
        fields.append(("Rejection Reason", f"[red]{item['rejection_reason']}[/red]"))
    if item.get("mcp_validated") is not None:
        badge = "[green]✓ Validated[/green]" if item["mcp_validated"] else "[red]✗ Not validated[/red]"
        fields.append(("MCP Validation", badge))
    if item.get("validation_results"):
        for vr in item["validation_results"]:
            passed = "[green]pass[/green]" if vr.get("passed") else "[red]fail[/red]"
            fields.append((f"  {vr.get('stage', '?')}", passed))
    console.print(kv_panel(item.get("name", "Review"), fields))


@review_app.command(name="approve")
def review_approve(
    review_id: str = typer.Argument(..., help="Name, row #, @alias, or UUID"),
    agent: bool = typer.Option(False, "--agent", "-a", help="Approve an agent (not a component)"),
    bundle: bool = typer.Option(False, "--bundle", "-b", help="Approve an entire bundle atomically"),
):
    """Approve a submission (component, agent, or bundle).

    After `observal admin review list`, use a row number (e.g. 1),
    the component/agent name, or a UUID prefix. Approved items become
    visible in the public registry.

    Examples:

        observal admin review approve 1

        observal admin review approve my-mcp-server

        observal admin review approve my-agent --agent

        observal admin review approve my-bundle --bundle
    """
    resolved = config.resolve_alias(review_id)
    if agent:
        path = f"/api/v1/review/agents/{resolved}/approve"
    elif bundle:
        path = f"/api/v1/review/bundles/{resolved}/approve"
    else:
        path = f"/api/v1/review/{resolved}/approve"
    with spinner("Approving..."):
        result = client.post(path)
    name = result.get("name", review_id)
    if bundle:
        rprint(f"[green]✓ Bundle approved: {name} ({result.get('approved_count', '?')} components)[/green]")
    else:
        rprint(f"[green]✓ Approved: {name}[/green]")


@review_app.command(name="reject")
def review_reject(
    review_id: str = typer.Argument(..., help="Name, row #, @alias, or UUID"),
    reason: str = typer.Option(..., "--reason", "-r", help="Rejection reason"),
    agent: bool = typer.Option(False, "--agent", "-a", help="Reject an agent (not a component)"),
    bundle: bool = typer.Option(False, "--bundle", "-b", help="Reject an entire bundle atomically"),
):
    """Reject a submission (component, agent, or bundle).

    After `observal admin review list`, use a row number (e.g. 1),
    the component/agent name, or a UUID prefix. A reason is required
    so the submitter understands why.

    Examples:

        observal admin review reject 2 --reason "Missing README"

        observal admin review reject my-agent --agent -r "Unsafe prompt"

        observal admin review reject my-bundle --bundle -r "License issue"
    """
    resolved = config.resolve_alias(review_id)
    if not reason.strip():
        rprint("[red]Rejection reason cannot be empty.[/red]")
        raise typer.Exit(1)
    if agent:
        path = f"/api/v1/review/agents/{resolved}/reject"
    elif bundle:
        path = f"/api/v1/review/bundles/{resolved}/reject"
    else:
        path = f"/api/v1/review/{resolved}/reject"
    with spinner("Rejecting..."):
        result = client.post(path, {"reason": reason})
    name = result.get("name", review_id)
    if bundle:
        rprint(f"[yellow]✗ Bundle rejected: {name} ({result.get('rejected_count', '?')} components)[/yellow]")
    else:
        rprint(f"[yellow]✗ Rejected: {name}[/yellow]")


# ── Telemetry ────────────────────────────────────────────

telemetry_app = typer.Typer(help="Telemetry commands")


@telemetry_app.command(name="status")
def telemetry_status():
    """Check telemetry data flow status.

    Shows server-side event counts (tool calls, interactions) for the
    last hour and local buffer statistics (pending, failed, sent events).
    Useful for verifying that the shim is forwarding telemetry correctly.

    Examples:

        observal ops telemetry status
    """
    with spinner("Checking telemetry..."):
        data = client.get("/api/v1/telemetry/status")
    rprint(f"  Status:       [green]{data.get('status', 'unknown')}[/green]")
    rprint(f"  Tool calls:   {data.get('tool_call_events', 0)} (last hour)")
    rprint(f"  Interactions: {data.get('agent_interaction_events', 0)} (last hour)")

    # Show local buffer stats
    try:
        from observal_cli.telemetry_buffer import stats as buffer_stats

        buf = buffer_stats()
        rprint()
        rprint("  [bold]Local Buffer[/bold]")
        rprint(f"  Pending:      {buf['pending']} events")
        if buf["failed"]:
            rprint(f"  Failed:       [red]{buf['failed']} events[/red]")
        if buf["sent"]:
            rprint(f"  Sent (cached):{buf['sent']} events")
        if buf["oldest_pending"]:
            rprint(f"  Oldest:       {buf['oldest_pending']} UTC")
        if buf["last_sync"]:
            rprint(f"  Last sync:    {buf['last_sync']} UTC")
        if buf["total"] == 0:
            rprint("  [dim]Buffer is empty (all events sent directly)[/dim]")
    except Exception:
        pass


@telemetry_app.command(name="test")
def telemetry_test():
    """Send a test telemetry event.

    Submits a synthetic tool call event to the server to verify that
    the telemetry ingestion pipeline is working end to end.

    Examples:

        observal ops telemetry test
    """
    with spinner("Sending test event..."):
        result = client.post(
            "/api/v1/telemetry/events",
            {
                "tool_calls": [
                    {
                        "mcp_server_id": "test-mcp",
                        "tool_name": "test_tool",
                        "status": "success",
                        "latency_ms": 42,
                        "ide": "test",
                    }
                ],
            },
        )
    rprint(f"[green]✓ Test event sent![/green] Ingested: {result.get('ingested', 0)}")


# ── Dashboard (on ops_app) ──────────────────────────────


@ops_app.command(name="overview")
def _overview(output: str = typer.Option("table", "--output", "-o")):
    """Show enterprise overview stats.

    Displays high-level platform totals: MCP servers, agents, users,
    tool calls, and agent interactions.

    Examples:

        observal ops overview

        observal ops overview --output json
    """
    with spinner("Loading overview..."):
        data = client.get("/api/v1/overview/stats")
    if output == "json":
        output_json(data)
        return
    rprint()
    rprint(f"  [bold cyan]MCP Servers[/bold cyan]     {data.get('total_mcps', 0)}")
    rprint(f"  [bold magenta]Agents[/bold magenta]          {data.get('total_agents', 0)}")
    rprint(f"  [bold]Users[/bold]           {data.get('total_users', 0)}")
    rprint(f"  [bold green]Tool calls[/bold green]      {data.get('total_tool_calls', 0)}")
    rprint(f"  [bold yellow]Interactions[/bold yellow]    {data.get('total_agent_interactions', 0)}")
    rprint()


@ops_app.command(name="metrics")
def _metrics(
    item_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    item_type: str = typer.Option("mcp", "--type", "-t", help="mcp or agent"),
    output: str = typer.Option("table", "--output", "-o"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Refresh every 5s"),
):
    """Show metrics for an MCP server or agent.

    Displays downloads, call counts, error rates, and latency percentiles
    for the specified item. Use --watch to auto-refresh every 5 seconds
    (Ctrl+C to stop).

    Examples:

        observal ops metrics my-mcp

        observal ops metrics my-agent --type agent

        observal ops metrics @mcp-alias --watch

        observal ops metrics my-mcp --output json
    """
    _metrics_impl(item_id, item_type, output, watch)


def _metrics_impl(item_id, item_type, output, watch):
    resolved = config.resolve_alias(item_id)

    def _fetch_and_print():
        if item_type == "agent":
            data = client.get(f"/api/v1/agents/{resolved}/metrics")
            if output == "json":
                output_json(data)
                return
            total = data.get("total_interactions", 0)
            rate = data.get("acceptance_rate") or 0
            rprint("\n  [bold]Agent Metrics[/bold]")
            rprint(f"  Interactions:   {total}")
            rprint(f"  Downloads:      {data.get('total_downloads', 0)}")
            rprint(f"  Acceptance:     [{'green' if rate > 0.7 else 'yellow' if rate > 0.4 else 'red'}]{rate:.1%}[/]")
            rprint(f"  Avg tool calls: {data.get('avg_tool_calls', 0)}")
            rprint(f"  Avg latency:    {(data.get('avg_latency_ms') or 0):.0f}ms")
        else:
            data = client.get(f"/api/v1/mcps/{resolved}/metrics")
            if output == "json":
                output_json(data)
                return
            err_rate = data.get("error_rate") or 0
            rprint("\n  [bold]MCP Metrics[/bold]")
            rprint(f"  Downloads:  {data.get('total_downloads', 0)}")
            rprint(f"  Total calls: {data.get('total_calls', 0)}")
            rprint(
                f"  Error rate:  [{'red' if err_rate > 0.1 else 'yellow' if err_rate > 0.01 else 'green'}]{err_rate:.2%}[/]"
            )
            rprint(f"  Avg latency: {(data.get('avg_latency_ms') or 0):.0f}ms")
            rprint(
                f"  Latency p50/p90/p99: {data.get('p50_latency_ms', 0)}/{data.get('p90_latency_ms', 0)}/{data.get('p99_latency_ms', 0)}ms"
            )
        rprint()

    if watch:
        try:
            while True:
                console.clear()
                rprint(f"[dim]Watching metrics for {resolved} (Ctrl+C to stop)[/dim]")
                _fetch_and_print()
                time.sleep(5)
        except KeyboardInterrupt:
            rprint("\n[dim]Stopped.[/dim]")
    else:
        with spinner("Loading metrics..."):
            pass
        _fetch_and_print()


@ops_app.command(name="top")
def _top(
    item_type: str = typer.Option("mcp", "--type", "-t", help="mcp or agent"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show top MCP servers or agents by usage.

    Lists the highest-download items in descending order. Defaults to
    MCP servers; use --type agent to see top agents instead.

    Examples:

        observal ops top

        observal ops top --type agent

        observal ops top --output json
    """
    _top_impl(item_type, output)


def _top_impl(item_type, output):
    endpoint = "/api/v1/overview/top-mcps" if item_type == "mcp" else "/api/v1/overview/top-agents"
    with spinner():
        data = client.get(endpoint)
    if output == "json":
        output_json(data)
        return
    if not data:
        rprint(f"[dim]No {item_type} data yet.[/dim]")
        return
    label = "MCP Servers" if item_type == "mcp" else "Agents"
    table = Table(title=f"Top {label}", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold")
    table.add_column("Downloads", justify="right")
    table.add_column("ID", style="dim", max_width=12)
    for i, item in enumerate(data, 1):
        table.add_row(str(i), item["name"], str(int(item["value"])), str(item["id"])[:8] + "…")
    console.print(table)


# ── Feedback (on ops_app) ────────────────────────────────


@ops_app.command(name="rate")
def _rate(
    listing_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    stars: int = typer.Option(..., "--stars", "-s", min=1, max=5, help="Rating 1-5"),
    listing_type: str = typer.Option("mcp", "--type", "-t", help="mcp or agent"),
    comment: str | None = typer.Option(None, "--comment", "-c"),
):
    """Rate an MCP server or agent.

    Submits a 1-5 star rating (with optional comment) for the specified
    item. Ratings are dual-written to PostgreSQL and ClickHouse.

    Examples:

        observal ops rate my-mcp --stars 5

        observal ops rate my-agent --type agent -s 4 -c "Great tool usage"
    """
    _rate_impl(listing_id, stars, listing_type, comment)


def _rate_impl(listing_id, stars, listing_type, comment):
    resolved = config.resolve_alias(listing_id)
    with spinner("Submitting rating..."):
        client.post(
            "/api/v1/feedback",
            {
                "listing_id": resolved,
                "listing_type": listing_type,
                "rating": stars,
                "comment": comment,
            },
        )
    rprint(f"[green]✓ Rated {star_rating(stars)}[/green]")


@ops_app.command(name="feedback")
def _feedback(
    listing_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    listing_type: str = typer.Option("mcp", "--type", "-t"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show feedback for an MCP server or agent.

    Displays the average rating, total review count, and individual
    reviews (stars + comments) for the given item.

    Examples:

        observal ops feedback my-mcp

        observal ops feedback my-agent --type agent

        observal ops feedback my-mcp --output json
    """
    _feedback_impl(listing_id, listing_type, output)


def _feedback_impl(listing_id, listing_type, output):
    resolved = config.resolve_alias(listing_id)
    with spinner():
        data = client.get(f"/api/v1/feedback/{listing_type}/{resolved}")
        summary = client.get(f"/api/v1/feedback/summary/{resolved}")

    if output == "json":
        output_json({"summary": summary, "reviews": data})
        return

    if not data:
        rprint("[dim]No feedback yet.[/dim]")
        return

    avg = summary.get("average_rating", 0)
    total = summary.get("total_reviews", 0)
    rprint(f"\n  {star_rating(round(avg))} [bold]{avg:.1f}[/bold]/5 ({total} reviews)\n")
    for fb in data:
        stars_str = star_rating(fb.get("rating", 0))
        comment = f"  {fb['comment']}" if fb.get("comment") else ""
        rprint(f"  {stars_str}{comment}")
    rprint()


# ── Admin ────────────────────────────────────────────────

admin_app = typer.Typer(help="Admin commands")


@admin_app.command(name="settings")
def admin_settings(output: str = typer.Option("table", "--output", "-o")):
    """List enterprise settings.

    Displays all configured key-value enterprise settings on the server.

    Examples:

        observal admin settings

        observal admin settings --output json
    """
    with spinner():
        data = client.get("/api/v1/admin/settings")
    if output == "json":
        output_json(data)
        return
    if not data:
        rprint("[dim]No settings configured.[/dim]")
        return
    table = Table(title="Enterprise Settings", show_lines=False, padding=(0, 1))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for item in data:
        table.add_row(item["key"], item["value"])
    console.print(table)


@admin_app.command(name="set")
def admin_set(
    key: str = typer.Argument(...),
    value: str = typer.Argument(...),
):
    """Set an enterprise setting.

    Creates or updates a key-value enterprise configuration entry
    on the server. Requires admin privileges.

    Examples:

        observal admin set max_agents_per_user 10

        observal admin set telemetry_retention_days 90
    """
    with spinner():
        client.put(f"/api/v1/admin/settings/{key}", {"value": value})
    rprint(f"[green]✓ {key} = {value}[/green]")


@admin_app.command(name="users")
def admin_users(output: str = typer.Option("table", "--output", "-o")):
    """List all users.

    Displays all registered users with their email, name, role, and ID.
    Requires admin privileges.

    Examples:

        observal admin users

        observal admin users --output json
    """
    with spinner():
        data = client.get("/api/v1/admin/users")
    if output == "json":
        output_json(data)
        return
    table = Table(title=f"Users ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Email")
    table.add_column("Name", style="bold")
    table.add_column("Role")
    table.add_column("ID", style="dim", max_width=12)
    for i, u in enumerate(data, 1):
        role_color = "green" if u["role"] == "admin" else "cyan" if u["role"] == "developer" else "white"
        table.add_row(
            str(i), u["email"], u["name"], f"[{role_color}]{u['role']}[/{role_color}]", str(u["id"])[:8] + "…"
        )
    console.print(table)


@admin_app.command(name="create-user")
def admin_create_user(
    email: str = typer.Argument(..., help="Email address for the new user"),
    name: str = typer.Argument(..., help="Full name of the user"),
    username: str = typer.Option(None, "--username", "-u", help="Username (optional)"),
    role: str = typer.Option("reviewer", "--role", "-r", help="Role: admin, reviewer, or user"),
    password: str = typer.Option(None, "--password", "-p", help="Password (auto-generated if omitted)"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Create a new user account. Requires admin privileges.

    If no password is provided, a secure random password will be generated.

    Examples:

        observal admin create-user alice@example.com "Alice Smith"

        observal admin create-user bob@example.com "Bob Jones" --role admin

        observal admin create-user carol@example.com "Carol Lee" -u carol -r reviewer -p s3cret
    """
    body: dict = {"email": email, "name": name, "role": role}
    if username:
        body["username"] = username
    if password:
        body["password"] = password

    with spinner("Creating user..."):
        data = client.post("/api/v1/admin/users", body)

    if output == "json":
        output_json(data)
        return

    rprint("\n[green]User created successfully.[/green]\n")
    rprint(f"  [bold]Name:[/bold]     {data['name']}")
    rprint(f"  [bold]Email:[/bold]    {data['email']}")
    if data.get("username"):
        rprint(f"  [bold]Username:[/bold] {data['username']}")
    rprint(f"  [bold]Role:[/bold]     {data['role']}")
    rprint(f"  [bold]ID:[/bold]       {data['id']}")
    rprint(f"\n[yellow]Password:[/yellow] {data['password']}")
    rprint("[dim]Save this, it will not be shown again.[/dim]")


@admin_app.command(name="reset-password")
def admin_reset_password(
    email: str = typer.Argument(..., help="Email of the user to reset"),
    generate: bool = typer.Option(False, "--generate", "-g", help="Generate a secure random password"),
):
    """Reset a user's password. Requires admin privileges.

    Provide the user's email and either enter a new password interactively
    or use --generate to create a secure random password.

    Examples:

        observal admin reset-password alice@example.com

        observal admin reset-password alice@example.com --generate
    """
    # Look up user ID by email
    with spinner("Looking up user..."):
        users = client.get("/api/v1/admin/users")
    match = next((u for u in users if u["email"] == email.strip().lower()), None)
    if not match:
        rprint(f"[red]User not found:[/red] {email}")
        raise typer.Exit(1)

    if generate:
        body: dict = {"generate": True}
    else:
        new_password = typer.prompt("New password", hide_input=True)
        confirm = typer.prompt("Confirm password", hide_input=True)
        if new_password != confirm:
            rprint("[red]Passwords do not match.[/red]")
            raise typer.Exit(1)
        body = {"new_password": new_password}

    with spinner("Resetting password..."):
        result = client.put(f"/api/v1/admin/users/{match['id']}/password", body)

    rprint(f"[green]{result['message']}[/green]")
    if "generated_password" in result:
        rprint(f"\n[yellow]Generated password:[/yellow] {result['generated_password']}")
        rprint("[dim]Save this, it will not be shown again.[/dim]")


@admin_app.command(name="delete-user")
def admin_delete_user(
    email: str = typer.Argument(..., help="Email of the user to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """Delete a user account. Requires admin privileges.

    This permanently removes the user and all associated data (API keys, etc.).

    Examples:

        observal admin delete-user alice@example.com

        observal admin delete-user alice@example.com --force
    """
    # Look up user ID by email
    with spinner("Looking up user..."):
        users = client.get("/api/v1/admin/users")
    match = next((u for u in users if u["email"] == email.strip().lower()), None)
    if not match:
        rprint(f"[red]User not found:[/red] {email}")
        raise typer.Exit(1)

    rprint(f"\n  [bold]{match['name']}[/bold] ({match['email']}), {match['role']}")
    if not force:
        typer.confirm("\nPermanently delete this user?", abort=True)

    with spinner("Deleting user..."):
        client.delete(f"/api/v1/admin/users/{match['id']}")

    rprint(f"[green]Deleted user {match['email']}[/green]")


# ── Diagnostics ─────────────────────────────────────────


@admin_app.command(name="diagnostics")
def admin_diagnostics(output: str = typer.Option("table", "--output", "-o")):
    """Show system diagnostics and health status.

    Reports overall system health, database connectivity, JWT key status,
    and enterprise configuration issues. Useful for troubleshooting
    deployment problems.

    Examples:

        observal admin diagnostics

        observal admin diagnostics --output json
    """
    with spinner():
        data = client.get("/api/v1/admin/diagnostics")
    if output == "json":
        output_json(data)
        return

    overall = data.get("status", "unknown")
    color = {"ok": "green", "degraded": "yellow", "unhealthy": "red"}.get(overall, "white")
    rprint(f"\n  Overall: [{color}]{overall}[/{color}]")
    rprint(f"  Mode:    {data.get('deployment_mode', 'unknown')}")

    checks = data.get("checks", {})

    db = checks.get("database", {})
    if db:
        db_color = "green" if db.get("status") == "ok" else "red"
        rprint(f"\n  Database: [{db_color}]{db.get('status', 'unknown')}[/{db_color}]")
        rprint(f"    Users: {db.get('users', '?')}")

    jwt_info = checks.get("jwt_keys", {})
    if jwt_info:
        jwt_color = "green" if jwt_info.get("status") == "ok" else "red"
        rprint(f"\n  JWT:     [{jwt_color}]{jwt_info.get('status', 'unknown')}[/{jwt_color}]")
        rprint(f"    Algorithm: {jwt_info.get('algorithm', '?')}")

    ee = checks.get("enterprise", {})
    if ee:
        issues = ee.get("issues", [])
        if issues:
            rprint("\n  [yellow]Enterprise issues:[/yellow]")
            for issue in issues:
                rprint(f"    - {issue}")
        else:
            rprint("\n  Enterprise: [green]ok[/green]")
    rprint()


# ── SAML Config ─────────────────────────────────────────


@admin_app.command(name="saml-config")
def admin_saml_config(output: str = typer.Option("table", "--output", "-o")):
    """View current SAML SSO configuration. (Enterprise only)

    Displays the IdP entity ID, SSO/SLO URLs, SP entity ID, and whether
    SAML and JIT provisioning are active.

    Examples:

        observal admin saml-config

        observal admin saml-config --output json
    """
    _require_enterprise()
    with spinner():
        data = client.get("/api/v1/admin/saml-config")
    if output == "json":
        output_json(data)
        return
    if not data or not data.get("configured"):
        rprint("[dim]SAML SSO is not configured.[/dim]")
        rprint("Use [bold]observal admin saml-config-set[/bold] to configure.")
        return

    rprint("\n[bold]SAML SSO Configuration[/bold]\n")
    for key in ("idp_entity_id", "idp_sso_url", "idp_slo_url", "sp_entity_id", "saml_active", "jit_provisioning"):
        val = data.get(key)
        if val is not None:
            display = "[green]Yes[/green]" if val is True else "[red]No[/red]" if val is False else str(val)
            rprint(f"  {key}: {display}")
    rprint()


@admin_app.command(name="saml-config-set")
def admin_saml_config_set(
    idp_entity_id: str = typer.Option(None, "--idp-entity-id", help="IdP Entity ID"),
    idp_sso_url: str = typer.Option(None, "--idp-sso-url", help="IdP SSO URL"),
    idp_slo_url: str = typer.Option(None, "--idp-slo-url", help="IdP SLO URL (optional)"),
    idp_x509_cert: str = typer.Option(None, "--idp-x509-cert", help="IdP X.509 certificate (PEM)"),
    sp_entity_id: str = typer.Option(None, "--sp-entity-id", help="SP Entity ID"),
    jit: bool = typer.Option(True, "--jit/--no-jit", help="Enable JIT user provisioning"),
    active: bool = typer.Option(True, "--active/--inactive", help="Enable SAML SSO"),
):
    """Create or update SAML SSO configuration.

    Examples:

        observal admin saml-config-set --idp-entity-id https://idp.example.com \\
            --idp-sso-url https://idp.example.com/sso \\
            --idp-x509-cert "$(cat idp-cert.pem)"
    """
    _require_enterprise()
    body: dict = {"saml_active": active, "jit_provisioning": jit}
    if idp_entity_id:
        body["idp_entity_id"] = idp_entity_id
    if idp_sso_url:
        body["idp_sso_url"] = idp_sso_url
    if idp_slo_url:
        body["idp_slo_url"] = idp_slo_url
    if idp_x509_cert:
        body["idp_x509_cert"] = idp_x509_cert
    if sp_entity_id:
        body["sp_entity_id"] = sp_entity_id

    with spinner("Updating SAML config..."):
        result = client.put("/api/v1/admin/saml-config", body)
    rprint("[green]SAML SSO configuration updated.[/green]")
    if result.get("sp_entity_id"):
        rprint(f"  SP Entity ID:  {result['sp_entity_id']}")
    if result.get("sp_acs_url"):
        rprint(f"  SP ACS URL:    {result['sp_acs_url']}")
    if result.get("sp_metadata_url"):
        rprint(f"  SP Metadata:   {result['sp_metadata_url']}")


@admin_app.command(name="saml-config-delete")
def admin_saml_config_delete(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """Delete SAML SSO configuration. Disables SAML SSO. (Enterprise only)

    Removes the entire SAML configuration, disabling SSO for all users.
    Prompts for confirmation unless --force is passed.

    Examples:

        observal admin saml-config-delete

        observal admin saml-config-delete --force
    """
    _require_enterprise()
    if not force:
        typer.confirm("This will disable SAML SSO for all users. Continue?", abort=True)
    with spinner("Deleting SAML config..."):
        client.delete("/api/v1/admin/saml-config")
    rprint("[green]SAML SSO configuration deleted.[/green]")


# ── SCIM Tokens ─────────────────────────────────────────


@admin_app.command(name="scim-tokens")
def admin_scim_tokens(output: str = typer.Option("table", "--output", "-o")):
    """List SCIM provisioning tokens. (Enterprise only)

    Shows all SCIM bearer tokens with their prefix, description,
    active status, and creation date.

    Examples:

        observal admin scim-tokens

        observal admin scim-tokens --output json
    """
    _require_enterprise()
    with spinner():
        data = client.get("/api/v1/admin/scim-tokens")
    if output == "json":
        output_json(data)
        return
    if not data:
        rprint("[dim]No SCIM tokens configured.[/dim]")
        rprint("Use [bold]observal admin scim-token-create[/bold] to create one.")
        return
    table = Table(title="SCIM Tokens", show_lines=False, padding=(0, 1))
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Prefix")
    table.add_column("Description")
    table.add_column("Active")
    table.add_column("Created")
    for t in data:
        active = "[green]Yes[/green]" if t.get("active") else "[red]No[/red]"
        created = t.get("created_at", "")[:10] if t.get("created_at") else "-"
        table.add_row(
            str(t.get("id", ""))[:8] + "...",
            t.get("token_prefix", ""),
            t.get("description", "-"),
            active,
            created,
        )
    console.print(table)


@admin_app.command(name="scim-token-create")
def admin_scim_token_create(
    description: str = typer.Option("", "--description", "-d", help="Token description"),
):
    """Create a new SCIM provisioning token.

    The token is shown once on creation. Save it securely. (Enterprise only)

    Examples:
        observal admin scim-token-create
        observal admin scim-token-create --description "Okta SCIM sync"
    """
    _require_enterprise()
    body: dict = {}
    if description:
        body["description"] = description
    with spinner("Creating SCIM token..."):
        result = client.post("/api/v1/admin/scim-tokens", body)
    rprint("[green]SCIM token created.[/green]")
    rprint(f"\n[yellow]Token:[/yellow] {result.get('token', '')}")
    rprint("[dim]Save this -- it will not be shown again.[/dim]")
    if result.get("description"):
        rprint(f"  Description: {result['description']}")


@admin_app.command(name="scim-token-revoke")
def admin_scim_token_revoke(
    token_id: str = typer.Argument(..., help="Token ID to revoke"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """Revoke a SCIM provisioning token. (Enterprise only)

    Permanently disables the specified SCIM token so it can no longer
    be used for provisioning. Prompts for confirmation unless --force.

    Examples:

        observal admin scim-token-revoke abc12345-uuid

        observal admin scim-token-revoke abc12345-uuid --force
    """
    _require_enterprise()
    if not force:
        typer.confirm(f"Revoke SCIM token {token_id[:8]}...?", abort=True)
    with spinner("Revoking SCIM token..."):
        client.delete(f"/api/v1/admin/scim-tokens/{token_id}")
    rprint(f"[green]SCIM token {token_id[:8]}... revoked.[/green]")


# ── Security Events ─────────────────────────────────────


@admin_app.command(name="security-events")
def admin_security_events(
    event_type: str = typer.Option(None, "--type", "-t", help="Filter by event type"),
    severity: str = typer.Option(None, "--severity", "-s", help="Filter: info, warning, critical"),
    actor: str = typer.Option(None, "--actor", "-a", help="Filter by actor email"),
    limit: int = typer.Option(50, "--limit", "-n"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """View security events log.

    Lists security-relevant events (login attempts, permission changes,
    etc.) with optional filters on type, severity, and actor.

    Examples:

        observal admin security-events

        observal admin security-events --type auth.login --severity critical

        observal admin security-events --actor alice@example.com -n 100

        observal admin security-events --output json
    """
    params: dict = {"limit": str(limit)}
    if event_type:
        params["event_type"] = event_type
    if severity:
        params["severity"] = severity
    if actor:
        params["actor_email"] = actor

    from urllib.parse import urlencode

    qs = f"?{urlencode(params)}" if params else ""
    with spinner():
        data = client.get(f"/api/v1/admin/security-events{qs}")
    events = data.get("events", data) if isinstance(data, dict) else data
    if output == "json":
        output_json(data)
        return
    if not events:
        rprint("[dim]No security events found.[/dim]")
        return
    table = Table(title=f"Security Events ({len(events)})", show_lines=False, padding=(0, 1))
    table.add_column("Time", style="dim", max_width=19)
    table.add_column("Type")
    table.add_column("Severity")
    table.add_column("Actor")
    table.add_column("Outcome")
    table.add_column("Detail", max_width=40)
    for ev in events:
        sev = ev.get("severity", "")
        sev_color = {"critical": "red", "warning": "yellow", "info": "dim"}.get(sev, "white")
        outcome = ev.get("outcome", "")
        outcome_color = "green" if outcome == "success" else "red" if outcome == "failure" else "white"
        ts = ev.get("timestamp", ev.get("created_at", ""))[:19]
        table.add_row(
            ts,
            ev.get("event_type", ""),
            f"[{sev_color}]{sev}[/{sev_color}]",
            ev.get("actor_email", "-"),
            f"[{outcome_color}]{outcome}[/{outcome_color}]",
            (ev.get("detail", "") or "")[:40],
        )
    console.print(table)


# ── Audit Log ───────────────────────────────────────────


@admin_app.command(name="audit-log")
def admin_audit_log(
    action: str = typer.Option(None, "--action", "-a", help="Filter by action (e.g. auth.login)"),
    actor: str = typer.Option(None, "--actor", help="Filter by actor email"),
    resource_type: str = typer.Option(None, "--resource-type", "-r", help="Filter by resource type"),
    limit: int = typer.Option(50, "--limit", "-n"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Query the audit log. (Enterprise only)

    Shows timestamped entries of admin and user actions with actor,
    resource, IP address, and detail fields. Supports filtering by
    action, actor, and resource type.

    Examples:

        observal admin audit-log

        observal admin audit-log --action auth.login --limit 100

        observal admin audit-log --actor alice@example.com -r agent

        observal admin audit-log --output json
    """
    _require_enterprise()
    from urllib.parse import urlencode

    params: dict = {"limit": str(limit)}
    if action:
        params["action"] = action
    if actor:
        params["actor_email"] = actor
    if resource_type:
        params["resource_type"] = resource_type

    qs = f"?{urlencode(params)}" if params else ""
    with spinner():
        data = client.get(f"/api/v1/admin/audit-log{qs}")
    if output == "json":
        output_json(data)
        return
    if not data:
        rprint("[dim]No audit log entries found.[/dim]")
        return
    table = Table(title=f"Audit Log ({len(data)} entries)", show_lines=False, padding=(0, 1))
    table.add_column("Time", style="dim", max_width=19)
    table.add_column("Actor")
    table.add_column("Action", style="bold")
    table.add_column("Resource")
    table.add_column("IP", style="dim")
    table.add_column("Detail", max_width=30)
    for entry in data:
        ts = entry.get("timestamp", entry.get("created_at", ""))[:19]
        resource = entry.get("resource_type", "")
        if entry.get("resource_name"):
            resource += f"/{entry['resource_name']}"
        table.add_row(
            ts,
            entry.get("actor_email", "-"),
            entry.get("action", ""),
            resource,
            entry.get("ip_address", "-"),
            (entry.get("detail", "") or "")[:30],
        )
    console.print(table)


@admin_app.command(name="audit-log-export")
def admin_audit_log_export(
    action: str = typer.Option(None, "--action", "-a", help="Filter by action"),
    actor: str = typer.Option(None, "--actor", help="Filter by actor email"),
    file: str = typer.Option(None, "--file", "-f", help="Write output to file"),
):
    """Export audit log as CSV. (Enterprise only)

    Downloads the audit log in CSV format. Prints to stdout by default,
    or writes to a file with --file.

    Examples:

        observal admin audit-log-export

        observal admin audit-log-export --file audit.csv

        observal admin audit-log-export --action auth.login --actor bob@example.com
    """
    _require_enterprise()
    from urllib.parse import urlencode

    params: dict = {}
    if action:
        params["action"] = action
    if actor:
        params["actor_email"] = actor

    qs = f"?{urlencode(params)}" if params else ""
    with spinner("Exporting audit log..."):
        data = client.get(f"/api/v1/admin/audit-log/export{qs}")

    if file:
        from pathlib import Path

        Path(file).write_text(data if isinstance(data, str) else str(data))
        rprint(f"[green]Audit log exported to {file}[/green]")
    else:
        rprint(data if isinstance(data, str) else str(data))


# ── Trace Privacy ───────────────────────────────────────


@admin_app.command(name="trace-privacy")
def admin_trace_privacy():
    """View trace privacy setting.

    Shows whether trace privacy (sensitive data redaction) is currently
    enabled or disabled for the organization.

    Examples:

        observal admin trace-privacy
    """
    with spinner():
        data = client.get("/api/v1/admin/org/trace-privacy")
    enabled = data.get("trace_privacy", False)
    status = "[green]enabled[/green]" if enabled else "[red]disabled[/red]"
    rprint(f"  Trace privacy: {status}")


@admin_app.command(name="trace-privacy-set")
def admin_trace_privacy_set(
    enabled: bool = typer.Argument(..., help="true or false"),
):
    """Enable or disable trace privacy (redacts sensitive trace data).

    When enabled, the server scrubs PII and secrets from stored traces.
    When disabled, traces are stored verbatim.

    Examples:

        observal admin trace-privacy-set true

        observal admin trace-privacy-set false
    """
    with spinner("Updating trace privacy..."):
        result = client.put("/api/v1/admin/org/trace-privacy", {"trace_privacy": enabled})
    status = "[green]enabled[/green]" if result.get("trace_privacy") else "[red]disabled[/red]"
    rprint(f"  Trace privacy: {status}")


# ── Cache ───────────────────────────────────────────────


@admin_app.command(name="cache-clear")
def admin_cache_clear():
    """Clear all server caches.

    Flushes all in-memory and Redis caches on the server. Useful after
    bulk data changes or when stale data is suspected.

    Examples:

        observal admin cache-clear
    """
    with spinner("Clearing caches..."):
        client.post("/api/v1/admin/cache/clear")
    rprint("[green]All caches cleared.[/green]")


# ── Role Update ─────────────────────────────────────────


@admin_app.command(name="set-role")
def admin_set_role(
    email: str = typer.Argument(..., help="Email of the user"),
    role: str = typer.Argument(..., help="New role: super_admin, admin, reviewer, or user"),
):
    """Change a user's role.

    Updates the role for the user identified by email. Valid roles are:
    super_admin, admin, reviewer, user. Requires admin privileges.

    Examples:

        observal admin set-role alice@example.com admin

        observal admin set-role bob@example.com reviewer
    """
    with spinner("Looking up user..."):
        users = client.get("/api/v1/admin/users")
    match = next((u for u in users if u["email"] == email.strip().lower()), None)
    if not match:
        rprint(f"[red]User not found:[/red] {email}")
        raise typer.Exit(1)
    with spinner("Updating role..."):
        result = client.put(f"/api/v1/admin/users/{match['id']}/role", {"role": role})
    rprint(f"[green]{result.get('email', email)} is now {result.get('role', role)}[/green]")


# ── Traces / Spans (on ops_app) ─────────────────────────


@ops_app.command(name="traces")
def _traces(
    trace_type: str | None = typer.Option(None, "--type", "-t"),
    mcp_id: str | None = typer.Option(None, "--mcp"),
    agent_id: str | None = typer.Option(None, "--agent"),
    limit: int = typer.Option(20, "--limit", "-n"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """List recent traces.

    Queries the GraphQL API for recent telemetry traces. Results can be
    filtered by trace type, MCP server, or agent. Shows span count,
    error count, and tool call count per trace.

    Examples:

        observal ops traces

        observal ops traces --type tool_call --limit 50

        observal ops traces --mcp my-mcp

        observal ops traces --agent my-agent --output json
    """
    _traces_impl(trace_type, mcp_id, agent_id, limit, output)


def _traces_impl(trace_type, mcp_id, agent_id, limit, output):
    variables = {"limit": limit}
    if trace_type:
        variables["traceType"] = trace_type
    if mcp_id:
        variables["mcpId"] = config.resolve_alias(mcp_id)
    if agent_id:
        variables["agentId"] = config.resolve_alias(agent_id)

    query = """query($traceType: String, $mcpId: String, $agentId: String, $limit: Int) {
        traces(traceType: $traceType, mcpId: $mcpId, agentId: $agentId, limit: $limit) {
            items {
                traceId traceType name mcpId agentId ide startTime
                metrics { totalSpans errorCount toolCallCount }
            }
        }
    }"""
    import httpx

    cfg = config.get_or_exit()
    with spinner("Querying traces..."):
        try:
            r = httpx.post(
                f"{cfg['server_url'].rstrip('/')}/api/v1/graphql",
                json={"query": query, "variables": variables},
                timeout=30,
            )
            r.raise_for_status()
            items = r.json().get("data", {}).get("traces", {}).get("items", [])
        except Exception as e:
            rprint(f"[red]Failed to query traces: {e}[/red]")
            raise typer.Exit(1)

    if output == "json":
        output_json(items)
        return

    if not items:
        rprint("[dim]No traces found.[/dim]")
        return

    table = Table(title=f"Traces ({len(items)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Trace ID", style="dim", max_width=14)
    table.add_column("Type")
    table.add_column("Name", no_wrap=True)
    table.add_column("Ref", style="dim", max_width=16)
    table.add_column("IDE")
    table.add_column("Spans", justify="right")
    table.add_column("Err", justify="right")
    table.add_column("Tools", justify="right")
    table.add_column("When")
    for i, t in enumerate(items, 1):
        m = t.get("metrics", {})
        ref = t.get("mcpId") or t.get("agentId") or "--"
        errs = m.get("errorCount", 0)
        err_style = "red" if errs > 0 else ""
        table.add_row(
            str(i),
            t["traceId"][:12] + "…",
            t.get("traceType", ""),
            t.get("name", "") or "--",
            ref[:16],
            t.get("ide", "") or "--",
            str(m.get("totalSpans", 0)),
            f"[{err_style}]{errs}[/{err_style}]" if err_style else str(errs),
            str(m.get("toolCallCount", 0)),
            relative_time(t.get("startTime")),
        )
    console.print(table)


@ops_app.command(name="spans")
def _spans(
    trace_id: str = typer.Argument(..., help="Trace ID"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """List spans for a trace.

    Shows all spans within a trace, including type, method, latency,
    status, and schema validation result. Use a trace ID from
    `observal ops traces` output.

    Examples:

        observal ops spans abc123-trace-id

        observal ops spans abc123-trace-id --output json
    """
    _spans_impl(trace_id, output)


def _spans_impl(trace_id, output):
    query = """query($traceId: String!) {
        trace(traceId: $traceId) {
            traceId name
            spans {
                spanId type name method latencyMs status
                toolSchemaValid toolsAvailable
            }
        }
    }"""
    import httpx

    cfg = config.get_or_exit()
    with spinner("Querying spans..."):
        try:
            r = httpx.post(
                f"{cfg['server_url'].rstrip('/')}/api/v1/graphql",
                json={"query": query, "variables": {"traceId": trace_id}},
                timeout=30,
            )
            r.raise_for_status()
            trace_data = r.json().get("data", {}).get("trace")
        except Exception as e:
            rprint(f"[red]Failed to query spans: {e}[/red]")
            raise typer.Exit(1)

    if not trace_data:
        rprint(f"[yellow]Trace {trace_id} not found.[/yellow]")
        raise typer.Exit(1)

    if output == "json":
        output_json(trace_data)
        return

    rprint(f"\n[bold]Trace:[/bold] {trace_data['traceId']}: {trace_data.get('name', '')}\n")

    spans_data = trace_data.get("spans", [])
    if not spans_data:
        rprint("[dim]No spans.[/dim]")
        return

    table = Table(show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Span ID", style="dim", max_width=14)
    table.add_column("Type")
    table.add_column("Name", no_wrap=True)
    table.add_column("Method")
    table.add_column("Latency", justify="right")
    table.add_column("Status")
    table.add_column("Schema")
    for i, s in enumerate(spans_data, 1):
        schema = (
            "[green]✓[/green]"
            if s.get("toolSchemaValid") is True
            else ("[red]✗[/red]" if s.get("toolSchemaValid") is False else "[dim]--[/dim]")
        )
        latency = f"{s['latencyMs']}ms" if s.get("latencyMs") else "--"
        st = s.get("status", "")
        st_display = f"[red]{st}[/red]" if st == "error" else f"[green]{st}[/green]" if st == "success" else st
        table.add_row(
            str(i),
            s["spanId"][:12] + "…",
            s.get("type", ""),
            s.get("name", ""),
            s.get("method", "") or "--",
            latency,
            st_display,
            schema,
        )
    console.print(table)


# ═══════════════════════════════════════════════════════════
# self_app: CLI self-management commands
# ═══════════════════════════════════════════════════════════

self_app = typer.Typer(
    name="self",
    help="CLI self-management commands (upgrade, downgrade, rollback, status)",
    no_args_is_help=True,
)


def _do_install(install_info, target_version: str, direction: str) -> None:
    """Execute the actual version change. Delegates to upgrade_executor module."""
    # Lazy import to avoid circular dependency (upgrade_executor imports from version_check)
    from observal_cli.upgrade_executor import execute

    execute(install_info, target_version, direction, spinner)


@self_app.command()
def upgrade(
    version: str | None = typer.Option(
        None, "--version", "-v", help="Target version to upgrade to (e.g. 0.9.0). Defaults to latest stable."
    ),
    pre: bool = typer.Option(False, "--pre", help="Include pre-release versions when resolving latest"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip interactive confirmation prompt"),
):
    """Upgrade the observal CLI to the latest (or specified) version.

    Downloads the new binary from GitHub releases, verifies its SHA-256
    checksum, and atomically replaces the current binary. A backup of
    the old version is kept for rollback.

    Managed installs (Homebrew, system packages) are detected and
    blocked with guidance to use the package manager instead.

    Examples:
        observal self upgrade
        observal self upgrade --version 0.9.0
        observal self upgrade --pre
        observal self upgrade --force
    """
    from packaging.version import InvalidVersion, Version

    from observal_cli import install_detector, version_check
    from observal_cli.install_detector import InstallMethod
    from observal_cli.upgrade_lock import UpgradeLockError, acquire_lock, release_lock

    current = version_check.get_current_version()
    install = install_detector.detect()

    # Block managed installs
    if install.method in (InstallMethod.HOMEBREW, InstallMethod.SYSTEM_PACKAGE):
        mgr = install.managed_by or "your package manager"
        rprint(f"[yellow]Observal is managed by {mgr}.[/yellow]")
        rprint(f"[dim]Upgrade with: {mgr} upgrade observal[/dim]")
        raise typer.Exit(1)

    # Resolve target
    if version:
        try:
            Version(version)
        except InvalidVersion:
            rprint(f"[red]Invalid version: {version}[/red]")
            raise typer.Exit(1)
        target = version
    else:
        with spinner("Checking for updates..."):
            rel = version_check._fetch_from_github(include_pre=pre)
        if not rel:
            rprint("[red]Failed to fetch latest release from GitHub.[/red]")
            raise typer.Exit(1)
        target = rel["latest_version"]

    if target == current:
        rprint(f"[green]Already on v{current} (latest).[/green]")
        raise typer.Exit(0)

    try:
        if Version(target) < Version(current):
            rprint(f"[yellow]v{target} is older than current v{current}.[/yellow]")
            rprint(f"[dim]Use: observal self downgrade --version {target}[/dim]")
            raise typer.Exit(1)
    except InvalidVersion:
        pass

    # Confirm
    if not force:
        rprint(f"  Current: [dim]v{current}[/dim]")
        rprint(f"  Target:  [green]v{target}[/green]")
        rprint(f"  Method:  [dim]{install.method.value} ({install.path})[/dim]")
        if not typer.confirm("\nProceed with upgrade?"):
            raise typer.Abort()

    # Lock + execute
    try:
        lock = acquire_lock("cli")
    except UpgradeLockError as e:
        rprint(f"[red]{e}[/red]")
        raise typer.Exit(1)
    try:
        _do_install(install, target, direction="upgrade")
    finally:
        release_lock(lock)


@self_app.command()
def downgrade(
    version: str | None = typer.Option(None, "--version", "-v", help="Target version to downgrade to (required)"),
    list_versions: bool = typer.Option(
        False, "--list", "-l", help="List all available versions with compatibility status"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """Downgrade the observal CLI to a previous version.

    Downloads and installs a specific older version from GitHub releases.

    Use --list to see all available versions with their publication dates
    and compatibility status.

    Examples:
        observal self downgrade --version 0.7.0
        observal self downgrade --list
        observal self downgrade --version 0.7.0 --force
    """
    from packaging.version import InvalidVersion, Version

    from observal_cli import install_detector, version_check
    from observal_cli.install_detector import InstallMethod
    from observal_cli.upgrade_lock import UpgradeLockError, acquire_lock, release_lock

    current = version_check.get_current_version()

    if list_versions:
        releases = version_check.fetch_all_releases()
        if not releases:
            rprint("[red]Failed to fetch releases from GitHub.[/red]")
            raise typer.Exit(1)

        table = Table(title="Available Versions")
        table.add_column("Version", style="bold")
        table.add_column("Published")
        table.add_column("Status")

        for r in releases:
            status = ""
            if r["version"] == current:
                status = "← current"
            table.add_row(r["version"], r.get("published_at", "")[:10], status)

        from rich.console import Console

        Console().print(table)
        raise typer.Exit(0)

    if not version:
        rprint("[red]--version is required for downgrade.[/red]")
        rprint("[dim]Use --list to see available versions.[/dim]")
        raise typer.Exit(1)

    try:
        target = Version(version)
    except InvalidVersion:
        rprint(f"[red]Invalid version: {version}[/red]")
        raise typer.Exit(1)

    try:
        if target >= Version(current):
            rprint(f"[yellow]v{version} is not older than current v{current}.[/yellow]")
            rprint("[dim]Use: observal self upgrade[/dim]")
            raise typer.Exit(1)
    except InvalidVersion:
        pass

    install = install_detector.detect()
    if install.method in (InstallMethod.HOMEBREW, InstallMethod.SYSTEM_PACKAGE):
        mgr = install.managed_by or "your package manager"
        rprint(f"[yellow]Observal is managed by {mgr}.[/yellow]")
        raise typer.Exit(1)

    if not force:
        rprint(f"  Current: [dim]v{current}[/dim]")
        rprint(f"  Target:  [yellow]v{version}[/yellow]")
        if not typer.confirm("\nProceed with downgrade?"):
            raise typer.Abort()

    try:
        lock = acquire_lock("cli")
    except UpgradeLockError as e:
        rprint(f"[red]{e}[/red]")
        raise typer.Exit(1)
    try:
        _do_install(install, version, direction="downgrade")
    finally:
        release_lock(lock)


@self_app.command()
def rollback():
    """Restore the CLI to the version before the last upgrade/downgrade.

    Copies the backed-up binary (saved during the previous upgrade) back
    over the current one. Only available for binary installs.

    Examples:
        observal self rollback
    """
    from observal_cli import install_detector
    from observal_cli.install_detector import InstallMethod

    install = install_detector.detect()
    backup = config.CONFIG_DIR / "bin" / "observal.prev"

    if not backup.exists():
        rprint("[red]No backup found. Nothing to rollback to.[/red]")
        raise typer.Exit(1)

    if install.method != InstallMethod.BINARY:
        rprint("[yellow]Rollback only supported for binary installs.[/yellow]")
        rprint(f"[dim]For {install.managed_by}: install the previous version explicitly.[/dim]")
        raise typer.Exit(1)

    import os
    import shutil

    target_path = install.path
    rprint(f"  Restore: {backup} → {target_path}")
    if not typer.confirm("Proceed?"):
        raise typer.Abort()

    shutil.copy2(str(backup), str(target_path))
    os.chmod(str(target_path), 0o755)
    rprint("[green]✓ Rolled back to previous version.[/green]")


@self_app.command()
def status():
    """Show current CLI version, install method, and update availability.

    Checks GitHub for the latest release and shows whether an update is
    available. Also displays the server's minimum CLI version requirement
    if connected.

    Examples:
        observal self status
    """
    from observal_cli import version_check

    current = version_check.get_current_version()
    rprint(f"  Version:  [bold]v{current}[/bold]")

    from observal_cli import install_detector

    install = install_detector.detect()
    rprint(f"  Install:  [dim]{install.method.value} ({install.path})[/dim]")

    # Always check (bypass OBSERVAL_NO_UPDATE_CHECK for explicit status command)
    with spinner("Checking for updates..."):
        rel = version_check._fetch_from_github()

    if rel:
        latest = rel["latest_version"]
        if version_check._is_newer(latest, current):
            rprint(f"  Latest:   [green]v{latest}[/green] (update available)")
            rprint("\n  Run: [bold]observal self upgrade[/bold]")
        else:
            rprint(f"  Latest:   [green]v{latest}[/green] (up to date)")
    else:
        rprint("  Latest:   [dim]could not reach GitHub[/dim]")


# ═══════════════════════════════════════════════════════════
# Wire sub-Typers into ops_app and admin_app
# ═══════════════════════════════════════════════════════════

# telemetry is a subgroup of ops
ops_app.add_typer(telemetry_app, name="telemetry")

# review is a subgroup of admin
admin_app.add_typer(review_app, name="review")
