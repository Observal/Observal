"""Review, telemetry, dashboard, feedback, eval, admin, and trace CLI commands."""

from __future__ import annotations

import time

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

# ═══════════════════════════════════════════════════════════
# ops_app — Observability / operational commands group
# ═══════════════════════════════════════════════════════════

ops_app = typer.Typer(
    name="ops",
    help="Observability and operational commands (traces, telemetry, dashboard, feedback)",
    no_args_is_help=True,
)


# ── Review ───────────────────────────────────────────────

review_app = typer.Typer(help="Admin review commands")


@review_app.command(name="list")
def review_list(output: str = typer.Option("table", "--output", "-o")):
    """List pending submissions."""
    with spinner("Fetching reviews..."):
        data = client.get("/api/v1/review")
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
    table.add_column("Name", style="bold")
    table.add_column("Submitted By")
    table.add_column("Status")
    table.add_column("ID", style="dim", no_wrap=True)
    for i, item in enumerate(data, 1):
        table.add_row(
            str(i),
            item.get("name", ""),
            item.get("submitted_by", ""),
            status_badge(item.get("status", "")),
            str(item["id"]),
        )
    console.print(table)


@review_app.command(name="show")
def review_show(review_id: str = typer.Argument(...), output: str = typer.Option("table", "--output", "-o")):
    """Show review details."""
    with spinner():
        item = client.get(f"/api/v1/review/{review_id}")
    if output == "json":
        output_json(item)
        return
    console.print(
        kv_panel(
            item.get("name", "Review"),
            [
                ("Status", status_badge(item.get("status", ""))),
                ("Submitted By", item.get("submitted_by", "N/A")),
                ("Git URL", item.get("git_url", "N/A")),
                ("Description", item.get("description", "")),
                ("ID", f"[dim]{item['id']}[/dim]"),
            ],
        )
    )


@review_app.command(name="approve")
def review_approve(review_id: str = typer.Argument(...)):
    """Approve a submission."""
    with spinner("Approving..."):
        result = client.post(f"/api/v1/review/{review_id}/approve")
    rprint(f"[green]✓ Approved: {result.get('name', review_id)}[/green]")


@review_app.command(name="reject")
def review_reject(
    review_id: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", "-r", help="Rejection reason"),
):
    """Reject a submission."""
    with spinner("Rejecting..."):
        result = client.post(f"/api/v1/review/{review_id}/reject", {"reason": reason})
    rprint(f"[yellow]✗ Rejected: {result.get('name', review_id)}[/yellow]")


# ── Telemetry ────────────────────────────────────────────

telemetry_app = typer.Typer(help="Telemetry commands")


@telemetry_app.command(name="status")
def telemetry_status():
    """Check telemetry data flow status."""
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
    """Send a test telemetry event."""
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


# ── Sync (on ops_app) ──────────────────────────────────


@ops_app.command(name="sync")
def ops_sync():
    """Flush locally buffered telemetry events to the server.

    When the Observal server is unreachable, hook events are stored in a
    local SQLite buffer (~/.observal/telemetry_buffer.db). This command
    sends pending events in batches and reports the result.
    """
    import httpx

    from observal_cli.telemetry_buffer import (
        BATCH_SIZE,
        cleanup,
        get_pending,
        mark_failed,
        mark_sent,
    )
    from observal_cli.telemetry_buffer import (
        stats as buffer_stats,
    )

    buf = buffer_stats()
    if buf["pending"] == 0:
        rprint("[dim]No pending events to sync.[/dim]")
        cleaned = cleanup()
        if cleaned:
            rprint(f"[dim]Cleaned up {cleaned} old sent events.[/dim]")
        return

    cfg = config.load()
    hooks_url = cfg.get("server_url", "http://localhost:8000").rstrip("/") + "/api/v1/otel/hooks"
    user_id = cfg.get("user_id", "")

    total_sent = 0
    total_failed = 0

    with spinner("Syncing buffered events..."):
        while True:
            batch = get_pending(limit=BATCH_SIZE)
            if not batch:
                break

            sent_ids = []
            failed_ids = []

            for event in batch:
                try:
                    headers = {"Content-Type": "application/json"}
                    if user_id:
                        headers["X-Observal-User-Id"] = user_id

                    r = httpx.post(
                        hooks_url,
                        content=event["payload"],
                        headers=headers,
                        timeout=5,
                    )
                    if r.status_code < 300:
                        sent_ids.append(event["id"])
                    else:
                        failed_ids.append(event["id"])
                except Exception:
                    failed_ids.append(event["id"])

            mark_sent(sent_ids)
            mark_failed(failed_ids)
            total_sent += len(sent_ids)
            total_failed += len(failed_ids)

            # If entire batch failed, server is probably down -- stop
            if not sent_ids:
                break

    remaining = buffer_stats()["pending"]
    cleaned = cleanup()

    rprint(
        f"[green]Synced {total_sent} events[/green], "
        f"[{'red' if total_failed else 'dim'}]{total_failed} failed[/], "
        f"[dim]{remaining} remaining[/dim]"
    )
    if cleaned:
        rprint(f"[dim]Cleaned up {cleaned} old sent events.[/dim]")


# ── Dashboard (on ops_app) ──────────────────────────────


@ops_app.command(name="overview")
def _overview(output: str = typer.Option("table", "--output", "-o")):
    """Show enterprise overview stats."""
    with spinner("Loading overview..."):
        data = client.get("/api/v1/overview/stats")
    if output == "json":
        output_json(data)
        return
    rprint()
    rprint(f"  [bold cyan]MCP Servers[/bold cyan]     {data.get('total_mcps', 0)}")
    rprint(f"  [bold magenta]Agents[/bold magenta]          {data.get('total_agents', 0)}")
    rprint(f"  [bold]Users[/bold]           {data.get('total_users', 0)}")
    rprint(f"  [bold green]Tool calls[/bold green]      {data.get('total_tool_calls_today', 0)} today")
    rprint(f"  [bold yellow]Interactions[/bold yellow]    {data.get('total_agent_interactions_today', 0)} today")
    rprint()


@ops_app.command(name="metrics")
def _metrics(
    item_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    item_type: str = typer.Option("mcp", "--type", "-t", help="mcp or agent"),
    output: str = typer.Option("table", "--output", "-o"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Refresh every 5s"),
):
    """Show metrics for an MCP server or agent."""
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
    """Show top MCP servers or agents by usage."""
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
    """Rate an MCP server or agent."""
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
    """Show feedback for an MCP server or agent."""
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


# ── Eval ─────────────────────────────────────────────────

eval_app = typer.Typer(help="Evaluation engine commands")


@eval_app.command(name="run")
def eval_run(
    agent_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    trace_id: str | None = typer.Option(None, "--trace"),
):
    """Run evaluation on an agent's traces."""
    resolved = config.resolve_alias(agent_id)
    body = {"trace_id": trace_id} if trace_id else {}
    with spinner("Running evaluation..."):
        result = client.post(f"/api/v1/eval/agents/{resolved}", body)
    rprint(f"\n[bold]Eval Run:[/bold] {result.get('id', 'N/A')}")
    rprint(f"  Status: {status_badge(result.get('status', 'unknown'))}")
    rprint(f"  Traces evaluated: {result.get('traces_evaluated', 0)}")
    for sc in result.get("scorecards", []):
        grade = sc.get("overall_grade", "?")
        score = sc.get("overall_score", 0)
        color = "green" if score >= 7 else "yellow" if score >= 4 else "red"
        rprint(f"  [{color}]{grade}[/{color}] {score:.1f}/10: {sc['id'][:8]}…")


@eval_app.command(name="scorecards")
def eval_scorecards(
    agent_id: str = typer.Argument(...),
    version: str | None = typer.Option(None, "--version", "-v"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """List scorecards for an agent."""
    resolved = config.resolve_alias(agent_id)
    params = {"version": version} if version else {}
    with spinner():
        data = client.get(f"/api/v1/eval/agents/{resolved}/scorecards", params=params)

    if output == "json":
        output_json(data)
        return

    if not data:
        rprint("[dim]No scorecards found.[/dim]")
        return

    table = Table(title=f"Scorecards ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Version", style="green")
    table.add_column("Score", justify="right")
    table.add_column("Grade")
    table.add_column("Bottleneck")
    table.add_column("When")
    table.add_column("ID", style="dim", max_width=12)
    for i, sc in enumerate(data, 1):
        score = sc.get("overall_score", 0)
        color = "green" if score >= 7 else "yellow" if score >= 4 else "red"
        table.add_row(
            str(i),
            sc.get("version", ""),
            f"[{color}]{score:.1f}[/{color}]",
            sc.get("overall_grade", ""),
            sc.get("bottleneck", "--"),
            relative_time(sc.get("evaluated_at")),
            str(sc["id"])[:8] + "…",
        )
    console.print(table)


@eval_app.command(name="show")
def eval_show(
    scorecard_id: str = typer.Argument(...),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show scorecard details with dimension breakdown."""
    with spinner():
        sc = client.get(f"/api/v1/eval/scorecards/{scorecard_id}")

    if output == "json":
        output_json(sc)
        return

    # Use new structured scoring if available, fall back to legacy
    grade = sc.get("grade") or sc.get("overall_grade", "?")
    composite = sc.get("composite_score")
    display = sc.get("display_score") or sc.get("overall_score", 0)
    grade_colors = {"A": "green", "B": "blue", "C": "yellow", "D": "#ff8c00", "F": "red"}
    gc = grade_colors.get(grade[0] if grade else "F", "red")

    header = f"Scorecard: [{gc}]{grade}[/{gc}] ({display:.1f}/10)"
    if composite is not None:
        header += f" [dim](composite: {composite:.1f}/100)[/dim]"

    recs = sc.get("scoring_recommendations") or []
    rec_str = sc.get("recommendations", "N/A")
    if recs:
        rec_str = "\n".join(f"  - {r}" for r in recs)

    console.print(
        kv_panel(
            header,
            [
                ("Bottleneck", sc.get("bottleneck", "N/A")),
                ("Penalties", str(sc.get("penalty_count", 0))),
                ("Recommendations", rec_str),
                ("ID", f"[dim]{sc['id']}[/dim]"),
            ],
            border_style=gc,
        )
    )

    # Show 5-dimension scores with colored bars
    dim_scores = sc.get("dimension_scores")
    if dim_scores:
        rprint("\n[bold]Dimension Scores (0-100):[/bold]")
        table = Table(show_header=True, show_lines=False, padding=(0, 1))
        table.add_column("Dimension", style="bold", width=20)
        table.add_column("Score", justify="right", width=6)
        table.add_column("Bar", width=30)
        for dim_name, dim_score in dim_scores.items():
            ds = float(dim_score)
            dc = (
                "green"
                if ds >= 85
                else "blue"
                if ds >= 70
                else "yellow"
                if ds >= 55
                else "#ff8c00"
                if ds >= 40
                else "red"
            )
            bar_len = int(ds / 100 * 25)
            bar = f"[{dc}]{'█' * bar_len}[/{dc}][dim]{'░' * (25 - bar_len)}[/dim]"
            table.add_row(dim_name, f"[{dc}]{ds:.0f}[/{dc}]", bar)
        console.print(table)
    else:
        # Legacy dimension display
        dims = sc.get("dimensions", [])
        if dims:
            rprint("\n[bold]Dimensions:[/bold]")
            table = Table(show_header=True, show_lines=False, padding=(0, 1))
            table.add_column("Dimension", style="bold")
            table.add_column("Score", justify="right", width=6)
            table.add_column("Grade", width=5)
            table.add_column("Notes")
            for dim in dims:
                ds = dim.get("score") or 0
                dc = "green" if ds >= 7 else "yellow" if ds >= 4 else "red"
                table.add_row(
                    dim.get("dimension", "?"),
                    f"[{dc}]{ds:.1f}[/{dc}]",
                    dim.get("grade", "?"),
                    dim.get("notes", ""),
                )
            console.print(table)

    # Show top penalties with evidence
    with spinner("Fetching penalties..."):
        try:
            penalties = client.get(f"/api/v1/eval/scorecards/{scorecard_id}/penalties")
        except Exception:
            penalties = []

    if penalties:
        rprint(f"\n[bold]Top Penalties ({len(penalties)} total):[/bold]")
        for p in penalties[:3]:
            severity_color = {"critical": "red", "moderate": "yellow", "minor": "dim"}.get(
                p.get("severity", ""), "white"
            )
            rprint(
                f"  [{severity_color}]{p.get('event_name', '?')}[/{severity_color}] "
                f"({p.get('amount', 0)}) — {p.get('evidence', '')[:120]}"
            )


@eval_app.command(name="compare")
def eval_compare(
    agent_id: str = typer.Argument(...),
    version_a: str = typer.Option(..., "--a"),
    version_b: str = typer.Option(..., "--b"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Compare two agent versions with dimension breakdown."""
    resolved = config.resolve_alias(agent_id)
    with spinner("Comparing versions..."):
        data = client.get(
            f"/api/v1/eval/agents/{resolved}/compare", params={"version_a": version_a, "version_b": version_b}
        )

    if output == "json":
        output_json(data)
        return

    a = data.get("version_a", {})
    b = data.get("version_b", {})
    sa, sb = a.get("avg_score", 0), b.get("avg_score", 0)
    diff = sb - sa
    arrow = "[green]↑[/green]" if diff > 0 else "[red]↓[/red]" if diff < 0 else "→"

    rprint("\n  [bold]Version Comparison[/bold]")
    rprint(f"  {a.get('version', '?'):>8}  →  {b.get('version', '?')}")
    rprint(f"  {sa:.1f}/10     {arrow}  {sb:.1f}/10  ({diff:+.1f})")
    rprint(f"  ({a.get('count', 0)} scorecards)    ({b.get('count', 0)} scorecards)")

    # Dimension-level comparison if available
    a_dims = a.get("dimension_averages", {})
    b_dims = b.get("dimension_averages", {})
    if a_dims and b_dims:
        rprint("\n  [bold]Dimension Breakdown:[/bold]")
        table = Table(show_header=True, show_lines=False, padding=(0, 1))
        table.add_column("Dimension", style="bold", width=20)
        table.add_column(a.get("version", "A"), justify="right", width=8)
        table.add_column(b.get("version", "B"), justify="right", width=8)
        table.add_column("Delta", width=10)
        for dim in sorted(set(list(a_dims.keys()) + list(b_dims.keys()))):
            va = float(a_dims.get(dim, 0))
            vb = float(b_dims.get(dim, 0))
            d = vb - va
            d_arrow = "[green]↑[/green]" if d > 0 else "[red]↓[/red]" if d < 0 else "→"
            table.add_row(dim, f"{va:.0f}", f"{vb:.0f}", f"{d_arrow} {d:+.0f}")
        console.print(table)
    rprint()


@eval_app.command(name="aggregate")
def eval_aggregate(
    agent_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    window: int = typer.Option(50, "--window", "-w", help="Number of recent scorecards"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show aggregate scoring stats for an agent."""
    resolved = config.resolve_alias(agent_id)
    with spinner("Computing aggregate..."):
        data = client.get(f"/api/v1/eval/agents/{resolved}/aggregate", params={"window_size": window})

    if output == "json":
        output_json(data)
        return

    mean = data.get("mean", 0)
    std = data.get("std", 0)
    ci_low = data.get("ci_low", 0)
    ci_high = data.get("ci_high", 0)
    drift = data.get("drift_alert", False)
    weakest = data.get("weakest_dimension", "N/A")

    rprint("\n  [bold]Agent Aggregate Scores[/bold]")
    rprint(f"  Mean composite:  {mean:.1f}/100")
    rprint(f"  Std dev:         {std:.1f}")
    rprint(f"  95% CI:          [{ci_low:.1f}, {ci_high:.1f}]")
    rprint(f"  Weakest dim:     {weakest}")
    drift_str = "[red]DRIFT DETECTED[/red]" if drift else "[green]Stable[/green]"
    rprint(f"  Drift status:    {drift_str}")

    dim_avgs = data.get("dimension_averages", {})
    if dim_avgs:
        rprint("\n  [bold]Dimension Averages:[/bold]")
        table = Table(show_header=True, show_lines=False, padding=(0, 1))
        table.add_column("Dimension", style="bold", width=20)
        table.add_column("Avg Score", justify="right", width=10)
        table.add_column("Bar", width=30)
        for dim, avg in sorted(dim_avgs.items()):
            ds = float(avg)
            dc = (
                "green"
                if ds >= 85
                else "blue"
                if ds >= 70
                else "yellow"
                if ds >= 55
                else "#ff8c00"
                if ds >= 40
                else "red"
            )
            bar_len = int(ds / 100 * 25)
            bar = f"[{dc}]{'█' * bar_len}[/{dc}][dim]{'░' * (25 - bar_len)}[/dim]"
            table.add_row(dim, f"[{dc}]{ds:.0f}[/{dc}]", bar)
        console.print(table)
    rprint()


# ── Admin ────────────────────────────────────────────────

admin_app = typer.Typer(help="Admin commands")


@admin_app.command(name="settings")
def admin_settings(output: str = typer.Option("table", "--output", "-o")):
    """List enterprise settings."""
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
    """Set an enterprise setting."""
    with spinner():
        client.put(f"/api/v1/admin/settings/{key}", {"value": value})
    rprint(f"[green]✓ {key} = {value}[/green]")


@admin_app.command(name="penalties")
def admin_penalties(output: str = typer.Option("table", "--output", "-o")):
    """List the penalty catalog."""
    with spinner():
        data = client.get("/api/v1/admin/penalties")
    if output == "json":
        output_json(data)
        return
    if not data:
        rprint("[dim]No penalties configured.[/dim]")
        return
    table = Table(title="Penalty Catalog", show_lines=False, padding=(0, 1))
    table.add_column("Event Name", style="bold")
    table.add_column("Dimension")
    table.add_column("Amount", justify="right")
    table.add_column("Severity")
    table.add_column("Active")
    for p in data:
        sev_color = {"critical": "red", "moderate": "yellow", "minor": "dim"}.get(p.get("severity", ""), "white")
        active = "[green]Yes[/green]" if p.get("is_active") else "[red]No[/red]"
        table.add_row(
            p["event_name"],
            p["dimension"],
            f"[{sev_color}]{p['amount']}[/{sev_color}]",
            f"[{sev_color}]{p['severity']}[/{sev_color}]",
            active,
        )
    console.print(table)


@admin_app.command(name="penalty-set")
def admin_penalty_set(
    penalty_name: str = typer.Argument(..., help="Penalty event_name or ID"),
    amount: int | None = typer.Option(None, "--amount", "-a"),
    active: bool | None = typer.Option(None, "--active"),
):
    """Modify a penalty definition."""
    # Look up by event name first
    with spinner():
        all_penalties = client.get("/api/v1/admin/penalties")
    match = next((p for p in all_penalties if p["event_name"] == penalty_name or p["id"] == penalty_name), None)
    if not match:
        rprint(f"[red]Penalty '{penalty_name}' not found.[/red]")
        raise typer.Exit(1)

    body: dict = {}
    if amount is not None:
        body["amount"] = amount
    if active is not None:
        body["is_active"] = active

    if not body:
        rprint("[yellow]No changes specified. Use --amount or --active.[/yellow]")
        return

    with spinner("Updating penalty..."):
        result = client.put(f"/api/v1/admin/penalties/{match['id']}", body)
    rprint(
        f"[green]Updated {result.get('event_name', penalty_name)}: amount={result.get('amount')}, active={result.get('is_active')}[/green]"
    )


@admin_app.command(name="weights")
def admin_weights(output: str = typer.Option("table", "--output", "-o")):
    """Show global dimension weights."""
    with spinner():
        data = client.get("/api/v1/admin/weights")
    if output == "json":
        output_json(data)
        return
    table = Table(title="Dimension Weights", show_lines=False, padding=(0, 1))
    table.add_column("Dimension", style="bold")
    table.add_column("Weight", justify="right")
    table.add_column("Custom")
    for w in data:
        custom = "[cyan]Custom[/cyan]" if w.get("is_custom") else "[dim]Default[/dim]"
        table.add_row(w["dimension"], f"{w['weight']:.2f}", custom)
    console.print(table)


@admin_app.command(name="weight-set")
def admin_weight_set(
    dimension: str = typer.Argument(..., help="Dimension name (e.g. goal_completion)"),
    weight: float = typer.Argument(..., help="New weight (0.0 - 1.0)"),
):
    """Set a global dimension weight."""
    with spinner("Updating weight..."):
        result = client.put("/api/v1/admin/weights", {dimension: weight})
    updated = result.get("updated", {})
    if dimension in updated:
        rprint(f"[green]Set {dimension} = {updated[dimension]}[/green]")
    else:
        rprint(f"[red]Unknown dimension: {dimension}[/red]")


@admin_app.command(name="users")
def admin_users(output: str = typer.Option("table", "--output", "-o")):
    """List all users."""
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


@admin_app.command(name="canaries")
def admin_canaries(
    agent_id: str = typer.Argument(..., help="Agent ID to list canaries for"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """List canary configs for an agent."""
    with spinner():
        data = client.get(f"/api/v1/admin/canaries/{agent_id}")
    if output == "json":
        output_json(data)
        return
    if not data:
        rprint(f"[dim]No canaries configured for agent {agent_id}.[/dim]")
        return
    table = Table(title=f"Canaries for {agent_id[:8]}...", show_lines=False, padding=(0, 1))
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Type", style="bold")
    table.add_column("Injection Point")
    table.add_column("Enabled")
    table.add_column("Expected Behavior")
    for c in data:
        enabled = "[green]Yes[/green]" if c.get("enabled") else "[red]No[/red]"
        table.add_row(
            str(c.get("id", ""))[:8] + "...",
            c.get("canary_type", ""),
            c.get("injection_point", ""),
            enabled,
            c.get("expected_behavior", ""),
        )
    console.print(table)


@admin_app.command(name="canary-add")
def admin_canary_add(
    agent_id: str = typer.Argument(..., help="Agent ID"),
    canary_type: str = typer.Option("numeric", "--type", "-t", help="numeric, entity, or instruction"),
    injection_point: str = typer.Option("tool_output", "--point", "-p", help="tool_output or context"),
    canary_value: str = typer.Option("", "--value", "-v", help="Canary value to inject"),
    expected: str = typer.Option("flag_anomaly", "--expected", "-e", help="Expected agent behavior"),
):
    """Add a canary config for an agent."""
    body = {
        "agent_id": agent_id,
        "canary_type": canary_type,
        "injection_point": injection_point,
        "canary_value": canary_value,
        "expected_behavior": expected,
    }
    with spinner("Creating canary..."):
        result = client.post("/api/v1/admin/canaries", body)
    rprint(f"[green]Canary created: id={result.get('id', '')[:8]}... type={result.get('canary_type')}[/green]")


@admin_app.command(name="canary-reports")
def admin_canary_reports(
    agent_id: str = typer.Argument(..., help="Agent ID"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show canary detection reports for an agent."""
    with spinner():
        data = client.get(f"/api/v1/admin/canaries/{agent_id}/reports")
    if output == "json":
        output_json(data)
        return
    if not data:
        rprint(f"[dim]No canary reports for agent {agent_id}.[/dim]")
        return
    table = Table(title=f"Canary Reports for {agent_id[:8]}...", show_lines=False, padding=(0, 1))
    table.add_column("Trace", style="dim", max_width=12)
    table.add_column("Type")
    table.add_column("Behavior", style="bold")
    table.add_column("Penalty")
    table.add_column("Evidence", max_width=40)
    for r in data:
        behavior = r.get("agent_behavior", "")
        behavior_color = {"parroted": "red", "flagged": "green", "ignored": "yellow", "corrected": "cyan"}.get(
            behavior, "white"
        )
        penalty = "[red]Yes[/red]" if r.get("penalty_applied") else "[green]No[/green]"
        table.add_row(
            str(r.get("trace_id", ""))[:8] + "...",
            r.get("canary_type", ""),
            f"[{behavior_color}]{behavior}[/{behavior_color}]",
            penalty,
            r.get("evidence", "")[:40],
        )
    console.print(table)


@admin_app.command(name="canary-delete")
def admin_canary_delete(
    canary_id: str = typer.Argument(..., help="Canary config ID to delete"),
):
    """Delete a canary config."""
    with spinner("Deleting canary..."):
        client.delete(f"/api/v1/admin/canaries/{canary_id}")
    rprint(f"[green]Canary {canary_id[:8]}... deleted.[/green]")


# ── Traces / Spans (on ops_app) ─────────────────────────


@ops_app.command(name="traces")
def _traces(
    trace_type: str | None = typer.Option(None, "--type", "-t"),
    mcp_id: str | None = typer.Option(None, "--mcp"),
    agent_id: str | None = typer.Option(None, "--agent"),
    limit: int = typer.Option(20, "--limit", "-n"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """List recent traces."""
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
    """List spans for a trace."""
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
# self_app — CLI self-management commands
# ═══════════════════════════════════════════════════════════

self_app = typer.Typer(
    name="self",
    help="CLI self-management commands (upgrade, downgrade)",
    no_args_is_help=True,
)


def _upgrade_impl():
    """Upgrade observal CLI to the latest version."""
    import subprocess

    with spinner("Upgrading..."):
        result = subprocess.run(
            ["uv", "tool", "upgrade", "observal-cli"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    if result.returncode == 0:
        rprint("[green]✓ Upgraded![/green]")
        if result.stdout.strip():
            rprint(f"[dim]{result.stdout.strip()}[/dim]")
    else:
        rprint(f"[red]Upgrade failed:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)


def _downgrade_impl():
    """Downgrade observal CLI to a previous version."""
    rprint("[yellow]WIP: not yet implemented.[/yellow]")
    rprint("[dim]Track: https://github.com/BlazeUp-AI/Observal/issues/19[/dim]")


@self_app.command()
def upgrade():
    """Upgrade observal CLI to the latest version."""
    _upgrade_impl()


@self_app.command()
def downgrade():
    """Downgrade observal CLI to a previous version."""
    _downgrade_impl()


# ═══════════════════════════════════════════════════════════
# Wire sub-Typers into ops_app and admin_app
# ═══════════════════════════════════════════════════════════

# telemetry is a subgroup of ops
ops_app.add_typer(telemetry_app, name="telemetry")

# review and eval are subgroups of admin
admin_app.add_typer(review_app, name="review")
admin_app.add_typer(eval_app, name="eval")
