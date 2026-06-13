# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""CLI commands for Agent Insights reports."""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table

from observal_cli import client, config
from observal_cli.render import console, output_json, relative_time, spinner, status_badge

insights_app = typer.Typer(help="Agent insight reports")


def _resolve_agent_id(agent_id: str) -> str:
    """Resolve an agent UUID, name, or alias to the canonical UUID."""
    resolved = config.resolve_alias(agent_id)
    agent = client.get(f"/api/v1/agents/{resolved}")
    return str(agent.get("id") or resolved)


def _select_report_id(reports: list[dict], report_ref: str | None) -> str:
    if not reports:
        rprint("[dim]No insight reports found.[/dim]")
        raise typer.Exit(1)

    if not report_ref or report_ref == "latest":
        completed = next((report for report in reports if report.get("status") == "completed"), None)
        return str((completed or reports[0])["id"])

    if report_ref.isdigit():
        index = int(report_ref)
        if 1 <= index <= len(reports):
            return str(reports[index - 1]["id"])
        rprint(f"[red]Report row {index} is out of range.[/red]")
        rprint(f"[dim]Choose a row from 1 to {len(reports)}.[/dim]")
        raise typer.Exit(1)

    matches = [report for report in reports if str(report.get("id", "")).lower().startswith(report_ref.lower())]
    if len(matches) == 1:
        return str(matches[0]["id"])
    if matches:
        rprint(f"[red]Report prefix '{report_ref}' is ambiguous.[/red]")
        rprint("[dim]Use the row number from `observal ops insights list <agent>` instead.[/dim]")
        raise typer.Exit(1)

    rprint(f"[red]Report '{report_ref}' was not found for this agent.[/red]")
    rprint("[dim]Use the row number from `observal ops insights list <agent>` instead.[/dim]")
    raise typer.Exit(1)


def _resolve_report_for_show(target: str, report_ref: str | None) -> dict:
    agent_id = _resolve_agent_id(target)
    reports = client.get(f"/api/v1/agents/{agent_id}/insights/reports")
    report_id = _select_report_id(reports, report_ref)
    return client.get(f"/api/v1/agents/{agent_id}/insights/reports/{report_id}")


@insights_app.command(name="list")
def insights_list(
    agent_id: str = typer.Argument(..., help="Agent ID, name, or @alias"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """List insight reports for an agent.

    Examples:

        observal ops insights list my-agent

        observal ops insights list my-agent --output json
    """
    with spinner("Fetching insight reports..."):
        resolved = _resolve_agent_id(agent_id)
        data = client.get(f"/api/v1/agents/{resolved}/insights/reports")
    if output == "json":
        output_json(data)
        return
    if not data:
        rprint("[dim]No insight reports found.[/dim]")
        return
    table = Table(title=f"Insight Reports ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Status")
    table.add_column("Version")
    table.add_column("Period")
    table.add_column("Sessions", justify="right")
    table.add_column("Completed")
    for i, r in enumerate(data, 1):
        start = r.get("period_start", "")[:10]
        end = r.get("period_end", "")[:10]
        table.add_row(
            str(i),
            status_badge(r.get("status", "")),
            str(r.get("agent_version") or "-"),
            f"{start} → {end}",
            str(r.get("sessions_analyzed", 0)),
            relative_time(r.get("completed_at")),
        )
    console.print(table)
    rprint()
    rprint(f"[dim]Open latest completed: [cyan]observal ops insights show {agent_id}[/cyan][/dim]")
    rprint(f"[dim]Open row 1: [cyan]observal ops insights show {agent_id} 1[/cyan][/dim]")


@insights_app.command(name="show")
def insights_show(
    target: str = typer.Argument(..., help="Agent name, agent ID, or @alias"),
    report_ref: str | None = typer.Argument(None, help="Report row number, report ID prefix, or 'latest'"),
    output: str = typer.Option("table", "--output", "-o"),
    section: str | None = typer.Option(None, "--section", "-s", help="Show only a specific section"),
):
    """Show an insight report with pretty-printed narrative.

    Examples:

        observal ops insights show my-agent

        observal ops insights show my-agent 3

        observal ops insights show my-agent --section suggestions

        observal ops insights show my-agent 3 --output json
    """
    with spinner("Fetching report..."):
        data = _resolve_report_for_show(target, report_ref)
    if output == "json":
        output_json(data)
        return
    if data.get("status") != "completed":
        rprint(f"  Status: {status_badge(data.get('status', 'unknown'))}")
        if data.get("progress_phase"):
            rprint(
                f"  Phase: [cyan]{str(data.get('progress_phase')).replace('_', ' ')}[/cyan] "
                f"({data.get('progress_percent', 0)}%)"
            )
        if data.get("progress_message"):
            rprint(f"  [dim]{data['progress_message']}[/dim]")
        if data.get("error_message"):
            rprint(f"  [red]Error:[/red] {data['error_message']}")
        return

    narrative = data.get("narrative") or {}
    if section:
        if section not in narrative:
            rprint(f"[red]Section '{section}' not found.[/red]")
            rprint(f"[dim]Available: {', '.join(narrative.keys())}[/dim]")
            raise typer.Exit(1)
        _render_section(section, narrative[section])
        return

    # Header
    start = data.get("period_start", "")[:10]
    end = data.get("period_end", "")[:10]
    rprint()
    version = data.get("agent_version") or "unknown"
    comparison = data.get("comparison_agent_version")
    comparison_text = f"  Compared to: v{comparison}" if comparison else ""
    rprint(f"  [bold]Insight Report[/bold]  v{version}  {start} → {end}")
    rprint(
        f"  Sessions: {data.get('sessions_analyzed', 0)}  Model: {data.get('llm_model_used', 'unknown')}"
        f"{comparison_text}"
    )
    rich = (data.get("metrics") or {}).get("rich") or {}
    if rich.get("cache_hit_rate_pct") is not None:
        rprint(f"  Cache: {rich.get('cache_hit_rate_pct')}% hit rate, {rich.get('cache_tokens_saved', 0)} tokens saved")
    rprint()

    # Render sections in logical order
    order = [
        "at_a_glance",
        "what_they_work_on",
        "interaction_style",
        "usage_patterns",
        "what_works",
        "friction_analysis",
        "suggestions",
        "usage_cost_analysis",
        "version_comparison",
        "regression_detection",
        "on_the_horizon",
        "fun_ending",
    ]
    for key in order:
        section_data = narrative.get(key)
        if section_data:
            _render_section(key, section_data)


# ──────────────────────────────────────────────────────────────────────────────
# Section renderers
# ──────────────────────────────────────────────────────────────────────────────

_SECTION_TITLES = {
    "at_a_glance": "⚡ At a Glance",
    "what_they_work_on": "📂 What You Work On",
    "interaction_style": "💬 Interaction Style",
    "usage_patterns": "📊 Usage Patterns",
    "what_works": "✅ What Works",
    "friction_analysis": "⚠️  Friction Analysis",
    "suggestions": "💡 Suggestions",
    "usage_cost_analysis": "💰 Cost Analysis",
    "version_comparison": "🧪 Version Comparison",
    "regression_detection": "📈 Regression Detection",
    "on_the_horizon": "🔮 On the Horizon",
    "fun_ending": "🎉 Fun Moment",
}

_HEALTH_COLORS = {"healthy": "green", "mixed": "yellow", "concerning": "red"}


def _render_section(name: str, data: dict | str | None):
    if not data:
        return
    title = _SECTION_TITLES.get(name, name.replace("_", " ").title())
    renderer = _RENDERERS.get(name)
    if renderer:
        renderer(title, data)
    elif isinstance(data, str):
        console.print(Panel(data, title=f"[bold]{title}[/bold]", border_style="blue", expand=False))
    elif isinstance(data, dict) and "narrative" in data:
        console.print(Panel(data["narrative"], title=f"[bold]{title}[/bold]", border_style="blue", expand=False))


def _render_at_a_glance(title: str, data: dict):
    health = data.get("health", "unknown")
    color = _HEALTH_COLORS.get(health, "white")
    lines = [f"[bold]Health:[/bold] [{color}]{health}[/{color}]", ""]
    if data.get("whats_working"):
        lines += [f"[green]What's working:[/green] {data['whats_working']}", ""]
    if data.get("whats_hindering"):
        lines += [f"[yellow]What's hindering:[/yellow] {data['whats_hindering']}", ""]
    if data.get("quick_win"):
        lines += [f"[cyan]Quick win:[/cyan] {data['quick_win']}", ""]
    if data.get("ambitious_workflows"):
        lines += [f"[magenta]Ambitious workflows:[/magenta] {data['ambitious_workflows']}"]
    console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="bright_blue", expand=False))


def _render_what_they_work_on(title: str, data: dict):
    areas = data.get("areas", [])
    if not areas:
        return
    table = Table(title=title, show_lines=False, padding=(0, 1))
    table.add_column("Area", style="bold")
    table.add_column("Sessions", justify="right")
    table.add_column("Description")
    for a in areas:
        table.add_row(a.get("name", ""), str(a.get("sessions", "")), a.get("description", ""))
    console.print(table)
    rprint()


def _render_interaction_style(title: str, data: dict):
    lines = []
    if data.get("narrative"):
        lines.append(data["narrative"])
    if data.get("key_pattern"):
        lines += ["", f"[bold]Key pattern:[/bold] [italic]{data['key_pattern']}[/italic]"]
    if lines:
        console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="blue", expand=False))


def _render_usage_patterns(title: str, data: dict):
    lines = []
    if data.get("narrative"):
        lines.append(data["narrative"])
    sp = data.get("session_profile", {})
    if sp:
        lines += [
            "",
            f"  Avg duration: [bold]{sp.get('avg_duration_minutes', '?')}m[/bold]"
            f"  Tool calls: [bold]{sp.get('avg_tool_calls', '?')}[/bold]"
            f"  Prompts: [bold]{sp.get('avg_prompts', '?')}[/bold]",
        ]
    if lines:
        console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="blue", expand=False))
    tools = data.get("tool_distribution", [])
    if tools:
        t = Table(show_lines=False, padding=(0, 1))
        t.add_column("Tool", style="bold")
        t.add_column("Calls", justify="right")
        t.add_column("Error %", justify="right")
        for tool in tools[:10]:
            err = tool.get("error_rate", 0)
            err_style = "red" if err > 0.1 else "yellow" if err > 0.01 else "green"
            t.add_row(tool.get("tool", ""), str(tool.get("calls", "")), f"[{err_style}]{err:.1%}[/{err_style}]")
        console.print(t)
        rprint()


def _render_what_works(title: str, data: dict):
    lines = []
    if data.get("intro"):
        lines.append(data["intro"])
    for s in data.get("strengths", []):
        lines += ["", f"  [green]●[/green] [bold]{s.get('title', '')}[/bold]", f"    {s.get('description', '')}"]
    if lines:
        console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="green", expand=False))


def _render_friction(title: str, data: dict):
    lines = []
    if data.get("intro"):
        lines.append(data["intro"])
    sev_colors = {"high": "red", "medium": "yellow", "low": "dim"}
    for cat in data.get("categories", []):
        sev = cat.get("severity", "medium")
        color = sev_colors.get(sev, "white")
        lines += ["", f"  [{color}]■ {cat.get('title', '')}[/{color}] [{color}]({sev})[/{color}]"]
        if cat.get("description"):
            lines.append(f"    {cat['description']}")
        for ex in cat.get("examples", []):
            lines.append(f"    [dim]• {ex}[/dim]")
        if cat.get("impact"):
            lines.append(f"    [dim]Impact: {cat['impact']}[/dim]")
    if lines:
        console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="yellow", expand=False))


def _render_suggestions(title: str, data: dict):
    # Config additions
    configs = data.get("config_additions", [])
    if configs:
        rprint(f"\n  [bold]{title} > Config Additions[/bold]")
        for c in configs:
            rprint(f"    [cyan]→[/cyan] {c.get('addition', '')}")
            rprint(f"      [dim]Why: {c.get('why', '')} | Where: {c.get('where', '')}[/dim]")

    # Features to try
    features = data.get("features_to_try", [])
    if features:
        rprint(f"\n  [bold]{title} > Features to Try[/bold]")
        for f in features:
            rprint(f"    [magenta]{f.get('feature', '')}:[/magenta] [bold]{f.get('name', '')}[/bold]")
            rprint(f"      {f.get('one_liner', '')}")
            if f.get("why_for_you"):
                rprint(f"      [dim]{f['why_for_you']}[/dim]")

    # Usage patterns
    patterns = data.get("usage_patterns", [])
    if patterns:
        rprint(f"\n  [bold]{title} > Usage Patterns[/bold]")
        for p in patterns:
            rprint(f"    [cyan]●[/cyan] [bold]{p.get('title', '')}[/bold]: {p.get('suggestion', '')}")
            if p.get("detail"):
                rprint(f"      [dim]{p['detail']}[/dim]")
            if p.get("copyable_prompt"):
                rprint(f"      [green]Try:[/green] {p['copyable_prompt']}")
    rprint()


def _render_cost(title: str, data: dict):
    lines = []
    if data.get("summary"):
        lines.append(data["summary"])
    m = data.get("metrics", {})
    if m:
        parts = []
        if m.get("total_cost_usd") is not None:
            parts.append(f"Total: ${m['total_cost_usd']:.2f}")
        if m.get("cost_per_session") is not None:
            parts.append(f"Per session: ${m['cost_per_session']:.3f}")
        if m.get("cache_efficiency_pct") is not None:
            parts.append(f"Cache: {m['cache_efficiency_pct']:.0f}%")
        if parts:
            lines += ["", "  " + "  │  ".join(parts)]
    opps = data.get("opportunities", [])
    for o in opps:
        lines += ["", f"  [yellow]●[/yellow] [bold]{o.get('title', '')}[/bold]"]
        if o.get("description"):
            lines.append(f"    {o['description']}")
        if o.get("estimated_savings"):
            lines.append(f"    [green]Savings: {o['estimated_savings']}[/green]")
    if lines:
        console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="blue", expand=False))


def _render_regression(title: str, data: dict):
    if not data.get("has_previous_data"):
        rprint(f"  [dim]{title}: No previous data for comparison.[/dim]")
        return
    lines = []
    if data.get("summary"):
        lines.append(data["summary"])
    for c in data.get("changes", []):
        direction = c.get("direction", "stable")
        icon = {"improved": "[green]↑[/green]", "degraded": "[red]↓[/red]", "stable": "[dim]→[/dim]"}.get(
            direction, "→"
        )
        sig = c.get("significance", "")
        sig_dim = f" [dim]({sig})[/dim]" if sig else ""
        lines.append(
            f"  {icon} [bold]{c.get('metric', '')}[/bold]: "
            f"{c.get('previous_value', '?')} → {c.get('current_value', '?')}{sig_dim}"
        )
    if lines:
        console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="blue", expand=False))


def _render_horizon(title: str, data: dict):
    lines = []
    if data.get("intro"):
        lines.append(data["intro"])
    for o in data.get("opportunities", []):
        lines += ["", f"  [magenta]●[/magenta] [bold]{o.get('title', '')}[/bold]"]
        if o.get("whats_possible"):
            lines.append(f"    {o['whats_possible']}")
        if o.get("how_to_try"):
            lines.append(f"    [cyan]Try:[/cyan] {o['how_to_try']}")
    if lines:
        console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="magenta", expand=False))


def _render_version_comparison(title: str, data: dict):
    lines = []
    if data.get("summary"):
        lines.append(data["summary"])
    if data.get("confidence"):
        lines.append(f"[dim]Confidence: {data['confidence']}[/dim]")
    for change in data.get("changes", [])[:6]:
        lines.append(
            f"\n[bold]{change.get('metric', '')}[/bold]: {change.get('direction', '')} "
            f"({change.get('prior_value', '?')} → {change.get('current_value', '?')})"
        )
        if change.get("attribution"):
            lines.append(f"[dim]Attribution: {change['attribution']}[/dim]")
        if change.get("evidence"):
            lines.append(f"[dim]{change['evidence']}[/dim]")
    if lines:
        console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="blue", expand=False))


def _render_fun_ending(title: str, data: dict):
    headline = data.get("headline", "")
    detail = data.get("detail", "")
    if headline:
        content = f"[italic]{headline}[/italic]"
        if detail:
            content += f"\n[dim]{detail}[/dim]"
        console.print(Panel(content, title=f"[bold]{title}[/bold]", border_style="bright_yellow", expand=False))


_RENDERERS = {
    "at_a_glance": _render_at_a_glance,
    "what_they_work_on": _render_what_they_work_on,
    "interaction_style": _render_interaction_style,
    "usage_patterns": _render_usage_patterns,
    "what_works": _render_what_works,
    "friction_analysis": _render_friction,
    "suggestions": _render_suggestions,
    "usage_cost_analysis": _render_cost,
    "version_comparison": _render_version_comparison,
    "regression_detection": _render_regression,
    "on_the_horizon": _render_horizon,
    "fun_ending": _render_fun_ending,
}


@insights_app.command(name="generate")
def insights_generate(
    agent_id: str = typer.Argument(..., help="Agent ID, name, or @alias"),
    period_days: int = typer.Option(14, "--period", "-p", help="Analysis period in days"),
    agent_version: str | None = typer.Option(None, "--version", "-v", help="Agent version to analyze"),
    compare_version: str | None = typer.Option(None, "--compare", help="Baseline agent version for A/B comparison"),
    output: str = typer.Option("table", "--output", "-o"),
    wait: bool = typer.Option(False, "--wait", help="Poll until the report completes"),
):
    """Trigger generation of a new insight report.

    Examples:

        observal ops insights generate my-agent

        observal ops insights generate my-agent --period 30
    """
    # Pre-check: verify insights is configured before queuing
    with spinner("Checking insights configuration..."):
        status = client.get("/api/v1/insights/status")
    if not status.get("available"):
        reason = status.get("reason", "Insights is not configured.")
        rprint(f"[red]✗ Insights not available:[/red] {reason}")
        rprint()
        rprint("  Configure with:")
        rprint("    [cyan]observal admin set insights.model_sections anthropic/claude-3-5-sonnet-20241022[/cyan]")
        rprint("    [cyan]observal admin set insights.api_key <your-api-key>[/cyan]")
        rprint()
        rprint("  [dim]Any LiteLLM-compatible model string works (OpenAI, Anthropic, Bedrock, Gemini, Ollama).[/dim]")
        rprint("  [dim]See: https://docs.litellm.ai/docs/providers[/dim]")
        raise typer.Exit(1)

    with spinner("Generating insight report..."):
        resolved = _resolve_agent_id(agent_id)
        body = {"period_days": period_days}
        if agent_version:
            body["agent_version"] = agent_version
        if compare_version:
            body["comparison_agent_version"] = compare_version
        data = client.post(f"/api/v1/agents/{resolved}/insights/reports", body)

    if wait and output != "json":
        import time

        report_id = str(data.get("id"))
        for _ in range(120):
            current = client.get(f"/api/v1/agents/{resolved}/insights/reports/{report_id}")
            phase = str(current.get("progress_phase") or current.get("status") or "queued").replace("_", " ")
            percent = current.get("progress_percent", 0)
            rprint(f"\r  {status_badge(current.get('status', 'pending'))} {phase} ({percent}%)", end="")
            if current.get("status") in {"completed", "failed"}:
                rprint()
                data = current
                break
            time.sleep(3)

    if output == "json":
        output_json(data)
        return
    rprint(f"[green]✓ Report queued[/green] (status: {status_badge(data.get('status', 'pending'))})")
    rprint(f"  ID: [dim]{data.get('id', '')}[/dim]")
    if data.get("agent_version"):
        rprint(f"  Version: v{data.get('agent_version')}")
    if data.get("comparison_agent_version"):
        rprint(f"  Compare: v{data.get('comparison_agent_version')}")
    rprint(f"  Period: {str(data.get('period_start', ''))[:10]} → {str(data.get('period_end', ''))[:10]}")
    if data.get("progress_phase"):
        rprint(f"  Phase: {str(data.get('progress_phase')).replace('_', ' ')} ({data.get('progress_percent', 0)}%)")
    rprint("[dim]  Run `observal ops insights show <agent>` when complete.[/dim]")
