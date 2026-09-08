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

"""Local harness inventory with opt-in interactive draft registration."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from loguru import logger as optic
from rich import print as rprint
from rich.table import Table

from observal_cli.discovery.collector import collect_discovery_scan, collect_legacy_scan
from observal_cli.discovery.redact import redact_arguments, redact_text, sanitize_diagnostic_message, sanitize_url
from observal_cli.discovery.registration import register_discovery_candidates, render_registration_results
from observal_cli.discovery.serialize import discovery_to_dict, legacy_scan_to_dict, privacy_safe_path
from observal_cli.harness import ensure_loaded, get_adapter, get_all_adapters
from observal_cli.render import OutputMode, console, esc, output_json, spinner

# ── CLI command ─────────────────────────────────────────────


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _safe_discovery_source(source: object, *, home: Path, project_dir: Path) -> str:
    value = str(source or "")
    path = Path(value).expanduser()
    if path.is_absolute():
        return privacy_safe_path(path, home=home, project_dir=project_dir)
    return redact_text(value)


def _safe_discovery_mcp_launch(mcp) -> str:
    if mcp.url:
        return sanitize_url(str(mcp.url)) or "<invalid-url>"
    command = redact_text(str(mcp.command or ""))
    arguments, _ = redact_arguments([str(item) for item in mcp.args])
    return " ".join((command, *arguments)).strip()


def _render_discovery_diagnostics(diagnostics) -> None:
    if not diagnostics:
        return
    table = Table(title=f"Discovery Diagnostics ({len(diagnostics)})", show_lines=False)
    table.add_column("Provider", style="cyan")
    table.add_column("Code", style="yellow")
    table.add_column("Message", style="dim")
    for diagnostic in diagnostics:
        table.add_row(
            esc(diagnostic.provider),
            diagnostic.code.value,
            esc(sanitize_diagnostic_message(diagnostic.message)),
        )
    console.print(table)
    rprint()


def register_scan(app: typer.Typer):
    @app.command(name="scan")
    def scan(
        harness: str | None = typer.Option(None, "--harness", "-i", help="Filter to a specific harness"),
        output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
        discover: bool = typer.Option(
            False,
            "--discover",
            help="Add bounded package evidence, local tracking, and authenticated Registry classification",
        ),
    ):
        """Show local inventory and optionally register discovered drafts.

        Scans all harness home directories and the current project directory to
        discover agents, MCP servers, skills, and hooks. Shows installed
        session telemetry hooks. Use --discover for bounded package evidence,
        local tracking state, authenticated Registry classification, and an
        optional interactive draft-registration flow.

        Use --harness to filter to a specific harness (e.g. --harness kiro).

        Scanning never modifies local files. JSON and non-interactive output
        never create Registry drafts. To install hooks, run:
          observal doctor patch --all-harnesses

        Examples:
            observal scan
            observal scan --harness claude-code
            observal scan --discover --output json
        """
        ensure_loaded()
        optic.trace("harness={}", harness)

        # Validate harness filter
        if harness:
            try:
                get_adapter(harness)
            except KeyError:
                valid = sorted(get_all_adapters().keys())
                if output == "json":
                    typer.echo(f"Unknown harness: {harness}", err=True)
                    typer.echo(f"Valid harnesses: {', '.join(valid)}", err=True)
                else:
                    rprint(f"[red]Unknown harness: {harness}[/red]")
                    rprint(f"Valid harnesses: {', '.join(valid)}")
                raise typer.Exit(1)

        adapters = {harness: get_adapter(harness)} if harness else get_all_adapters()
        home = Path.home()
        project_dir = Path(".").resolve()
        candidates = []
        diagnostics = []
        if discover:
            discovery_collection = collect_discovery_scan(
                adapters,
                home=home,
                project_dir=project_dir,
                harness_filtered=harness is not None,
            )
            collection = discovery_collection
            candidates = discovery_collection.candidates
            diagnostics = discovery_collection.diagnostics
        else:
            collection = collect_legacy_scan(
                adapters,
                home=home,
                project_dir=project_dir,
                scan_context=None if output == "json" else spinner,
            )
        all_mcps = collection.mcps
        all_skills = collection.skills
        all_hooks = collection.hooks
        all_agents = collection.agents
        ide_status = [(status.name, status.hooks) for status in collection.harnesses]
        total = collection.component_count

        if not collection.has_findings:
            if output == "json":
                if discover:
                    output_json(
                        discovery_to_dict(
                            harnesses=[],
                            mcps=[],
                            skills=[],
                            hooks=[],
                            agents=[],
                            candidates=candidates,
                            diagnostics=diagnostics,
                        )
                    )
                else:
                    output_json({"harnesses": [], "mcps": [], "skills": [], "hooks": [], "agents": []})
                return
            if discover:
                _render_discovery_diagnostics(diagnostics)
            rprint("[yellow]No harness configurations found.[/yellow]")
            raise typer.Exit(1)

        # JSON keeps the established keys and component record shapes.
        if output == "json":
            harnesses = [{"name": name, "hooks": hooks} for name, hooks in ide_status]
            if discover:
                output_json(
                    discovery_to_dict(
                        harnesses=harnesses,
                        mcps=all_mcps,
                        skills=all_skills,
                        hooks=all_hooks,
                        agents=all_agents,
                        candidates=candidates,
                        diagnostics=diagnostics,
                    )
                )
            else:
                output_json(
                    legacy_scan_to_dict(
                        harnesses=harnesses,
                        mcps=all_mcps,
                        skills=all_skills,
                        hooks=all_hooks,
                        agents=all_agents,
                    )
                )
            return

        if discover:
            rprint(
                f"\n[bold]Observal Discovery[/bold] - {total} components and {len(candidates)} candidates discovered\n"
            )
        else:
            rprint(f"\n[bold]Observal Scan[/bold] - {total} components discovered\n")

        # ── harnesses Detected table ──
        if ide_status:
            tbl = Table(title="harnesses Detected", show_lines=False, padding=(0, 1))
            tbl.add_column("harness", style="bold")
            tbl.add_column("Hooks", style="cyan")
            for name, hooks_s in ide_status:
                hooks_style = "green" if hooks_s == "installed" else ("yellow" if hooks_s == "partial" else "red")
                tbl.add_row(name, f"[{hooks_style}]{hooks_s}[/{hooks_style}]")
            console.print(tbl)
            rprint()

        # ── MCP Servers table ──
        if all_mcps:
            tbl = Table(title=f"MCP Servers ({len(all_mcps)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Name", style="bold")
            tbl.add_column("Command/URL", style="dim")
            tbl.add_column("Source", style="cyan")
            for m in all_mcps:
                launch = _safe_discovery_mcp_launch(m) if discover else m.display_cmd()
                source = _safe_discovery_source(m.source, home=home, project_dir=project_dir) if discover else m.source
                tbl.add_row(esc(redact_text(m.name)) if discover else m.name, esc(launch), esc(source))
            console.print(tbl)
            rprint()

        # ── Skills summary ──
        if all_skills:
            by_plugin: dict[str, int] = {}
            for s in all_skills:
                source = _safe_discovery_source(s.source, home=home, project_dir=project_dir) if discover else s.source
                by_plugin[source] = by_plugin.get(source, 0) + 1
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
                source = _safe_discovery_source(h.source, home=home, project_dir=project_dir) if discover else h.source
                if discover:
                    tbl.add_row(esc(redact_text(h.name)), esc(redact_text(h.event)), esc(source))
                else:
                    tbl.add_row(h.name, h.event, source)
            console.print(tbl)
            rprint()

        # ── Agents table ──
        if all_agents:
            tbl = Table(title=f"Agents ({len(all_agents)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Name", style="bold")
            tbl.add_column("Model", style="cyan")
            tbl.add_column("Description", style="dim", max_width=60)
            for a in all_agents:
                if discover:
                    tbl.add_row(
                        esc(redact_text(a.name)),
                        esc(redact_text(a.model_name or "-")),
                        esc(redact_text(a.description)[:60]),
                    )
                else:
                    tbl.add_row(a.name, a.model_name or "-", a.description[:60])
            console.print(tbl)
            rprint()

        registration_results = []
        if discover and _stdin_is_tty():
            registration_results = register_discovery_candidates(candidates, output=output, stdin_is_tty=True)
            render_registration_results(registration_results)

        if discover:
            if candidates:
                tbl = Table(title=f"Discovery Candidates ({len(candidates)})", show_lines=False, padding=(0, 1))
                tbl.add_column("Type", style="cyan")
                tbl.add_column("Name", style="bold")
                tbl.add_column("Tracking")
                tbl.add_column("Registry")
                tbl.add_column("Readiness")
                for candidate in candidates:
                    tbl.add_row(
                        candidate.component_type.value if candidate.component_type else "unknown",
                        esc(candidate.local_name),
                        candidate.tracking_status.value,
                        candidate.registry_status.value,
                        candidate.registration_status.value,
                    )
                console.print(tbl)
                rprint()
            _render_discovery_diagnostics(diagnostics)

        # ── Unregistered components (if authenticated) ──
        if not discover:
            try:
                from observal_cli import config as obs_config

                cfg = obs_config.load()
                if cfg.get("access_token") and cfg.get("server_url"):
                    import httpx

                    server_url = cfg["server_url"].rstrip("/")
                    headers = {"Authorization": f"Bearer {cfg['access_token']}"}

                    def registered_names(endpoint: str) -> set[str] | None:
                        try:
                            response = httpx.get(f"{server_url}/api/v1/{endpoint}", headers=headers, timeout=5)
                            if response.status_code != 200:
                                return None
                            return {item.get("name", "") for item in response.json() if isinstance(item, dict)}
                        except Exception:
                            return None

                    registered_mcps = registered_names("mcp")
                    registered_skills = registered_names("skills")
                    registered_agents = registered_names("agents")

                    unregistered: list[tuple[str, str]] = []
                    if registered_mcps is not None:
                        unregistered.extend(("mcp", item.name) for item in all_mcps if item.name not in registered_mcps)
                    if registered_skills is not None:
                        unregistered.extend(
                            ("skill", item.name) for item in all_skills if item.name not in registered_skills
                        )
                    if registered_agents is not None:
                        unregistered.extend(
                            ("agent", item.name) for item in all_agents if item.name not in registered_agents
                        )

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
        missing_hooks = any(h in ("missing", "partial") for _, h in ide_status)

        suggestions = []
        if missing_hooks:
            suggestions.append("Run [bold]observal doctor patch --all-harnesses[/bold] to install telemetry hooks")

        suggestions.append("Use [bold]observal registry <type> submit[/bold] to publish components to the registry")

        if suggestions:
            rprint("[dim]" + " | ".join(suggestions) + "[/dim]")

        if any(result.failed for result in registration_results):
            raise typer.Exit(1)
