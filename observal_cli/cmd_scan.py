"""observal scan: auto-detect IDE configs, register items, wrap with telemetry shims."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client
from observal_cli.render import console, spinner

# IDE config file locations (relative to project root)
_IDE_MCP_CONFIGS = {
    "cursor": ".cursor/mcp.json",
    "kiro": ".kiro/settings/mcp.json",
    "vscode": ".vscode/mcp.json",
    "claude-code": ".claude/mcp.json",
    "gemini-cli": ".gemini/settings.json",
}


def _detect_ide(project_dir: Path) -> list[tuple[str, Path]]:
    """Return list of (ide_name, config_path) for detected IDE configs."""
    found = []
    for ide, rel in _IDE_MCP_CONFIGS.items():
        p = project_dir / rel
        if p.exists():
            found.append((ide, p))
    return found


def _parse_mcp_servers(config: dict, ide: str) -> dict[str, dict]:
    """Extract mcpServers dict from IDE config, handling format differences."""
    if ide == "gemini-cli":
        return config.get("mcpServers", {})
    # cursor, kiro, vscode, claude-code all use mcpServers at top level
    return config.get("mcpServers", config.get("servers", {}))


def _is_already_shimmed(entry: dict) -> bool:
    """Check if an MCP entry is already wrapped with observal-shim."""
    cmd = entry.get("command", "")
    args = entry.get("args", [])
    if cmd == "observal-shim" or "observal-shim" in cmd:
        return True
    return bool(any("observal-shim" in str(a) for a in args))


def _wrap_with_shim(entry: dict, mcp_id: str) -> dict:
    """Wrap an MCP server entry with observal-shim for telemetry."""
    if entry.get("url"):
        # HTTP transport — can't shim stdio, leave as-is for now
        # The proxy approach would need observal-proxy, skip for scan
        return entry

    original_cmd = entry.get("command", "")
    original_args = entry.get("args", [])

    shimmed = dict(entry)
    shimmed["command"] = "observal-shim"
    shimmed["args"] = ["--mcp-id", mcp_id, "--", original_cmd, *original_args]
    return shimmed


def _backup_config(config_path: Path) -> Path:
    """Create a timestamped backup of the config file."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = config_path.with_suffix(f".pre-observal.{ts}.bak")
    shutil.copy2(config_path, backup)
    return backup


def register_scan(app: typer.Typer):
    @app.command(name="scan")
    def scan(
        project_dir: str = typer.Argument(".", help="Project directory to scan"),
        ide: str | None = typer.Option(None, "--ide", "-i", help="Target IDE (auto-detected if omitted)"),
        dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would change without modifying files"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ):
        """Scan existing IDE configs, register items in Observal, and wrap with telemetry shims.

        Detects MCP servers from your IDE config files, registers them with Observal,
        and rewrites configs to route through observal-shim for telemetry collection.
        Your existing setup keeps working — the shim is transparent.
        """
        root = Path(project_dir).resolve()
        if not root.is_dir():
            rprint(f"[red]Not a directory: {root}[/red]")
            raise typer.Exit(1)

        # Detect IDEs
        detected = _detect_ide(root)
        if ide:
            detected = [(i, p) for i, p in detected if i == ide]

        if not detected:
            rprint("[yellow]No IDE configs found.[/yellow]")
            rprint(f"[dim]Looked for: {', '.join(_IDE_MCP_CONFIGS.values())}[/dim]")
            raise typer.Exit(1)

        rprint(f"\n[bold]Scanning {root}[/bold]\n")

        all_items = []  # (ide, name, entry, config_path)
        for ide_name, config_path in detected:
            try:
                config = json.loads(config_path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                rprint(f"[yellow]⚠ Could not parse {config_path}: {e}[/yellow]")
                continue

            servers = _parse_mcp_servers(config, ide_name)
            if not servers:
                rprint(f"[dim]{ide_name}: no MCP servers found in {config_path}[/dim]")
                continue

            for name, entry in servers.items():
                if _is_already_shimmed(entry):
                    rprint(f"  [dim]⊘ {name} (already shimmed)[/dim]")
                    continue
                all_items.append((ide_name, name, entry, config_path))

        if not all_items:
            rprint("[green]✓ Nothing to do — all items already instrumented or no items found.[/green]")
            return

        # Show what we found
        table = Table(title=f"Found {len(all_items)} MCP servers to instrument", show_lines=False, padding=(0, 1))
        table.add_column("IDE", style="cyan")
        table.add_column("Name", style="bold")
        table.add_column("Command/URL", style="dim")
        for ide_name, name, entry, _ in all_items:
            cmd = entry.get("url") or f"{entry.get('command', '?')} {' '.join(entry.get('args', [])[:3])}"
            if len(cmd) > 60:
                cmd = cmd[:57] + "..."
            table.add_row(ide_name, name, cmd)
        console.print(table)
        rprint()

        if dry_run:
            rprint("[yellow]Dry run — no changes made.[/yellow]")
            return

        if not yes and not typer.confirm("Register and instrument these items?"):
            raise typer.Abort()

        # Group by IDE for bulk registration
        by_ide: dict[str, list[tuple[str, dict, Path]]] = {}
        for ide_name, name, entry, config_path in all_items:
            by_ide.setdefault(ide_name, []).append((name, entry, config_path))

        total_registered = 0
        total_shimmed = 0

        for ide_name, items in by_ide.items():
            # Bulk register via /api/v1/scan
            scan_payload = {
                "ide": ide_name,
                "mcps": [
                    {
                        "name": name,
                        "command": entry.get("command"),
                        "args": entry.get("args", []),
                        "url": entry.get("url"),
                        "env": entry.get("env", {}),
                    }
                    for name, entry, _ in items
                ],
            }

            with spinner(f"Registering {len(items)} items for {ide_name}..."):
                try:
                    result = client.post("/api/v1/scan", scan_payload)
                except (Exception, SystemExit) as e:
                    rprint(f"[red]✗ Failed to register items for {ide_name}: {e}[/red]")
                    continue

            # Build name -> id mapping
            id_map = {}
            for reg in result.get("registered", []):
                id_map[reg["name"]] = reg["id"]
                status_icon = "[green]✓ new[/green]" if reg["status"] == "created" else "[cyan]↻ existing[/cyan]"
                rprint(f"  {status_icon} {reg['name']} → {reg['id'][:8]}…")
                total_registered += 1

            # Rewrite config files
            configs_to_update: dict[str, dict] = {}  # path -> full config
            for name, _entry, config_path in items:
                mcp_id = id_map.get(name)
                if not mcp_id:
                    continue

                path_str = str(config_path)
                if path_str not in configs_to_update:
                    configs_to_update[path_str] = json.loads(config_path.read_text())

                config = configs_to_update[path_str]
                servers = _parse_mcp_servers(config, ide_name)
                if name in servers and not _is_already_shimmed(servers[name]):
                    servers[name] = _wrap_with_shim(servers[name], mcp_id)
                    total_shimmed += 1

            # Write updated configs
            for path_str, config in configs_to_update.items():
                config_path = Path(path_str)
                backup = _backup_config(config_path)
                config_path.write_text(json.dumps(config, indent=2) + "\n")
                rprint(f"  [dim]Backup: {backup.name}[/dim]")

        rprint(
            f"\n[green]✓ Done![/green] Registered {total_registered} items, instrumented {total_shimmed} with telemetry."
        )
        rprint("[dim]Your existing tools still work exactly the same — observal-shim is transparent.[/dim]")
        rprint("[dim]Telemetry flows to Observal even without admin approval.[/dim]")
