# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Devaansh Dubey <devaanshdubey@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 Madhumidha <madhumidha072005@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""observal scan: read-only inventory of local harness setup."""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

import typer
from loguru import logger as optic
from rich import print as rprint
from rich.table import Table

from observal_cli.harness import (
    DiscoveredMcp,
    NotSupportedError,
    ensure_loaded,
    get_adapter,
    get_all_adapters,
)
from observal_cli.render import console, spinner
from observal_cli.shared.utils import is_already_shimmed as _is_already_shimmed

# ── harness home directory paths (for status display) ────────────────

_HARNESS_HOME_DIRS: dict[str, str] = {
    "claude-code": "~/.claude",
    "kiro": "~/.kiro",
    "codex": "~/.codex",
    "copilot": "~/.vscode",
    "copilot-cli": "~/.copilot",
    "opencode": "~/.config/opencode",
    "antigravity": "~/.gemini",
    "cursor": "~/.cursor",
    "pi": "~/.pi/agent",
}


def _mcp_shim_status(mcps: list[DiscoveredMcp]) -> str:
    """Return shim summary like '3 of 5 shimmed' or 'all shimmed'."""
    total = 0
    shimmed = 0
    for m in mcps:
        if m.url:
            continue
        total += 1
        cmd = m.command or ""
        args_str = " ".join(str(a) for a in m.args)
        if "observal-shim" in cmd or "observal-shim" in args_str:
            shimmed += 1
    if total == 0:
        return "n/a"
    if shimmed == total:
        return "all shimmed"
    if shimmed == 0:
        return "no shims"
    return f"{shimmed} of {total} shimmed"


# ── CLI command ─────────────────────────────────────────────


def register_scan(app: typer.Typer):
    @app.command(name="scan")
    def scan(
        harness: str | None = typer.Option(None, "--harness", "-i", help="Filter to a specific harness"),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table or json"),
    ):
        """Show a read-only inventory of your local harness setup.

        Scans all harness home directories and the current project directory to
        discover agents, MCP servers, skills, and hooks. Shows what's
        instrumented (hooks/shims) and what's missing.

        Use --harness to filter to a specific harness (e.g. --harness kiro).

        This command never modifies files. To instrument, run:
          observal doctor patch --all --all-harnesses

        Examples:
            observal scan
            observal scan --harness claude-code
            observal scan --harness kiro
        """
        ensure_loaded()
        optic.trace("harness={}", harness)

        # Validate harness filter
        if harness:
            try:
                get_adapter(harness)
            except KeyError:
                valid = sorted(get_all_adapters().keys())
                rprint(f"[red]Unknown harness: {harness}[/red]")
                rprint(f"Valid harnesses: {', '.join(valid)}")
                raise typer.Exit(1)

        adapters = {harness: get_adapter(harness)} if harness else get_all_adapters()
        home = Path.home()
        project_dir = Path(".").resolve()

        all_mcps: list[DiscoveredMcp] = []
        all_skills = []
        all_hooks = []
        all_agents = []
        seen_mcp_names: set[str] = set()
        ide_status: list[tuple[str, str, str]] = []  # (name, hooks, shims)

        for ide_name, adapter in adapters.items():
            home_label = _HARNESS_HOME_DIRS.get(ide_name, "")
            home_dir = Path(home_label.replace("~", str(home))) if home_label else None

            # Skip if home dir doesn't exist
            if home_dir and not home_dir.is_dir():
                continue

            # Suppress the scanning spinner in JSON mode to prevent stdout pollution
            scan_ctx = nullcontext() if output == "json" else spinner(f"Scanning {home_label or ide_name}...")
            with scan_ctx:
                try:
                    home_result = adapter.scan_home(home)
                except NotSupportedError:
                    home_result = type("R", (), {"mcps": [], "skills": [], "hooks": [], "agents": []})()

                try:
                    proj_result = adapter.scan_project(project_dir)
                except NotSupportedError:
                    proj_result = type("R", (), {"mcps": [], "skills": [], "hooks": [], "agents": []})()

            # Merge with deduplication
            for mcp in home_result.mcps + proj_result.mcps:
                if mcp.name not in seen_mcp_names:
                    all_mcps.append(mcp)
                    seen_mcp_names.add(mcp.name)
            all_skills.extend(home_result.skills + proj_result.skills)
            all_hooks.extend(home_result.hooks + proj_result.hooks)
            all_agents.extend(home_result.agents + proj_result.agents)

            # Determine status for this harness
            try:
                config_dir = home_dir or (home / ".config" / ide_name)
                hook_status = adapter.detect_hooks(config_dir)
            except NotSupportedError:
                hook_status = "n/a"
            shim_stat = _mcp_shim_status(home_result.mcps + proj_result.mcps)
            ide_status.append((ide_name, hook_status, shim_stat))

        # Also scan home as project if different from cwd
        if project_dir != home:
            for _ide_name, adapter in adapters.items():
                try:
                    extra = adapter.scan_project(home)
                    for mcp in extra.mcps:
                        if mcp.name not in seen_mcp_names:
                            all_mcps.append(mcp)
                            seen_mcp_names.add(mcp.name)
                except NotSupportedError:
                    pass

        total = len(all_mcps) + len(all_skills) + len(all_hooks) + len(all_agents)

        if total == 0 and not ide_status:
            if output == "json":
                print(json.dumps({"harnesses": [], "mcps": [], "skills": [], "hooks": [], "agents": []}, indent=2))
                return
            rprint("[yellow]No harness configurations found.[/yellow]")
            raise typer.Exit(1)

        # In JSON mode, dump the raw discovered objects and exit before rendering rich tables
        if output == "json":
            out_data = {
                "harnesses": [{"name": n, "hooks": h, "shims": s} for n, h, s in ide_status],
                "mcps": [vars(m) for m in all_mcps],
                "skills": [vars(s) for s in all_skills],
                "hooks": [vars(h) for h in all_hooks],
                "agents": [vars(a) for a in all_agents],
            }
            print(json.dumps(out_data, indent=2))
            return

        rprint(f"\n[bold]Observal Scan[/bold] - {total} components discovered\n")

        # ── harnesses Detected table ──
        if ide_status:
            tbl = Table(title="harnesses Detected", show_lines=False, padding=(0, 1))
            tbl.add_column("harness", style="bold")
            tbl.add_column("Hooks", style="cyan")
            tbl.add_column("Shims", style="cyan")
            for name, hooks_s, shims_s in ide_status:
                hooks_style = "green" if hooks_s == "installed" else ("yellow" if hooks_s == "partial" else "red")
                shims_style = (
                    "green"
                    if shims_s == "all shimmed"
                    else ("yellow" if "of" in shims_s else ("dim" if shims_s == "n/a" else "red"))
                )
                tbl.add_row(
                    name,
                    f"[{hooks_style}]{hooks_s}[/{hooks_style}]",
                    f"[{shims_style}]{shims_s}[/{shims_style}]",
                )
            console.print(tbl)
            rprint()

        # ── MCP Servers table ──
        if all_mcps:
            tbl = Table(title=f"MCP Servers ({len(all_mcps)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Name", style="bold")
            tbl.add_column("Command/URL", style="dim")
            tbl.add_column("Source", style="cyan")
            tbl.add_column("Shimmed", style="cyan")
            for m in all_mcps:
                is_shimmed = _is_already_shimmed({"command": m.command or "", "args": m.args})
                shimmed_label = "[green]yes[/green]" if is_shimmed else ("[dim]n/a[/dim]" if m.url else "[red]no[/red]")
                tbl.add_row(m.name, m.display_cmd(), m.source, shimmed_label)
            console.print(tbl)
            rprint()

        # ── Skills summary ──
        if all_skills:
            by_plugin: dict[str, int] = {}
            for s in all_skills:
                by_plugin[s.source] = by_plugin.get(s.source, 0) + 1
            tbl = Table(title=f"Skills ({len(all_skills)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Source Plugin", style="cyan")
            tbl.add_column("Count", style="bold", justify="right")
            for src, count in sorted(by_plugin.items()):
                tbl.add_row(src, str(count))
            console.print(tbl)
            rprint()

        # ── Hooks table ──
        if all_hooks:
            tbl = Table(title=f"Hooks ({len(all_hooks)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Name", style="bold")
            tbl.add_column("Event", style="cyan")
            tbl.add_column("Source", style="dim")
            for h in all_hooks:
                tbl.add_row(h.name, h.event, h.source)
            console.print(tbl)
            rprint()

        # ── Agents table ──
        if all_agents:
            tbl = Table(title=f"Agents ({len(all_agents)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Name", style="bold")
            tbl.add_column("Model", style="cyan")
            tbl.add_column("Description", style="dim", max_width=60)
            for a in all_agents:
                tbl.add_row(a.name, a.model_name or "-", a.description[:60])
            console.print(tbl)
            rprint()

        # ── Unregistered components (if authenticated) ──
        try:
            from observal_cli import config as obs_config

            cfg = obs_config.load()
            if cfg.get("access_token") and cfg.get("server_url"):
                import httpx

                server_url = cfg["server_url"].rstrip("/")
                headers = {"Authorization": f"Bearer {cfg['access_token']}"}

                registered_mcps: set[str] = set()
                registered_skills: set[str] = set()
                registered_agents: set[str] = set()

                try:
                    r = httpx.get(f"{server_url}/api/v1/mcp", headers=headers, timeout=5)
                    if r.status_code == 200:
                        for item in r.json():
                            registered_mcps.add(item.get("name", ""))
                except Exception:
                    pass
                try:
                    r = httpx.get(f"{server_url}/api/v1/skills", headers=headers, timeout=5)
                    if r.status_code == 200:
                        for item in r.json():
                            registered_skills.add(item.get("name", ""))
                except Exception:
                    pass
                try:
                    r = httpx.get(f"{server_url}/api/v1/agents", headers=headers, timeout=5)
                    if r.status_code == 200:
                        for item in r.json():
                            registered_agents.add(item.get("name", ""))
                except Exception:
                    pass

                unregistered: list[tuple[str, str]] = []
                for m in all_mcps:
                    if m.name not in registered_mcps:
                        unregistered.append(("mcp", m.name))
                for s in all_skills:
                    if s.name not in registered_skills:
                        unregistered.append(("skill", s.name))
                for a in all_agents:
                    if a.name not in registered_agents:
                        unregistered.append(("agent", a.name))

                if unregistered:
                    from observal_cli import client as obs_client

                    _reg_only_enabled = obs_client.get_registered_agents_only()

                    if _reg_only_enabled:
                        rprint(
                            "[yellow bold]⚠ Registered-agents-only mode is ON.[/yellow bold] "
                            "Unregistered components below will NOT be traced."
                        )
                        rprint()

                    tbl = Table(
                        title=f"Unregistered Components ({len(unregistered)})", show_lines=False, padding=(0, 1)
                    )
                    tbl.add_column("Type", style="yellow")
                    tbl.add_column("Name", style="bold")
                    for comp_type, comp_name in unregistered[:30]:
                        tbl.add_row(comp_type, comp_name)
                    if len(unregistered) > 30:
                        tbl.add_row("...", f"and {len(unregistered) - 30} more")
                    console.print(tbl)
                    rprint()
        except Exception:
            pass

        # ── Footer with suggestions ──
        missing_hooks = any(h == "missing" or h == "partial" for _, h, _ in ide_status)
        missing_shims = any(s not in ("all shimmed", "n/a") for _, _, s in ide_status)

        suggestions = []
        if missing_hooks and missing_shims:
            suggestions.append("Run [bold]observal doctor patch --all --all-harnesses[/bold] to instrument everything")
        elif missing_hooks:
            suggestions.append(
                "Run [bold]observal doctor patch --hook --all-harnesses[/bold] to install telemetry hooks"
            )
        elif missing_shims:
            suggestions.append("Run [bold]observal doctor patch --shim --all-harnesses[/bold] to wrap MCP servers")

        suggestions.append("Use [bold]observal registry <type> submit[/bold] to publish components to the registry")

        if suggestions:
            rprint("[dim]" + " | ".join(suggestions) + "[/dim]")
