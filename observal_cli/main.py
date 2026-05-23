# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Observal CLI: MCP Server & Agent Registry."""

import atexit
import logging
import os
import sys

if sys.platform == "win32" and not os.environ.get("PYTHONIOENCODING"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import typer

from observal_cli.cmd_auth import version_callback


def _check_package_conflict() -> None:
    """Warn if the legacy 'observal' package is installed alongside 'observal-cli'."""
    from importlib.metadata import PackageNotFoundError, metadata

    try:
        meta = metadata("observal")
    except PackageNotFoundError:
        return

    # If we get here, a package literally named "observal" exists.
    # Check it's not just our own package under a different dist name.
    pkg_name = meta.get("Name", "")
    if pkg_name.lower() == "observal-cli":
        return

    from rich import print as rprint

    rprint(
        "[bold yellow]⚠ Package conflict detected:[/bold yellow] "
        "Both [bold]observal[/bold] and [bold]observal-cli[/bold] are installed.\n"
        "  The legacy [dim]observal[/dim] package is no longer maintained and conflicts with the CLI.\n"
        "  Please uninstall it:\n\n"
        "    [cyan]uv pip uninstall observal[/cyan]    [dim]# or: pip uninstall observal[/dim]\n"
    )
    sys.exit(1)


_check_package_conflict()

# ── Version callback for --version flag ───────────────────


def _version_option(value: bool):
    if value:
        version_callback()
        raise typer.Exit()


app = typer.Typer(
    name="observal",
    help="Observal: MCP Server & Agent Registry CLI",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        help="Show CLI version and exit.",
        callback=_version_option,
        is_eager=True,
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    debug: bool = typer.Option(False, "--debug", help="Debug logging"),
):
    """Observal: MCP Server & Agent Registry CLI"""
    if debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    elif verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# ── Register command groups ──────────────────────────────

from observal_cli.cmd_agent import agent_app
from observal_cli.cmd_auth import auth_app, register_config
from observal_cli.cmd_component import component_app
from observal_cli.cmd_doctor import doctor_app
from observal_cli.cmd_hook import hook_app
from observal_cli.cmd_mcp import mcp_app
from observal_cli.cmd_migrate import migrate_app
from observal_cli.cmd_models import models_app
from observal_cli.cmd_ops import (
    admin_app,
    ops_app,
    self_app,
)
from observal_cli.cmd_profile import register_use
from observal_cli.cmd_prompt import prompt_app
from observal_cli.cmd_pull import register_pull
from observal_cli.cmd_sandbox import sandbox_app
from observal_cli.cmd_scan import register_scan
from observal_cli.cmd_skill import skill_app
from observal_cli.cmd_support import support_app
from observal_cli.cmd_uninstall import register_uninstall

# ═══════════════════════════════════════════════════════════
# registry_app — Component registry parent group
# ═══════════════════════════════════════════════════════════

registry_app = typer.Typer(
    name="registry",
    help="Component registry (MCPs, skills, hooks, prompts, sandboxes)",
    no_args_is_help=True,
)

registry_app.add_typer(mcp_app, name="mcp")
registry_app.add_typer(skill_app, name="skill")
registry_app.add_typer(hook_app, name="hook")
registry_app.add_typer(prompt_app, name="prompt")
registry_app.add_typer(sandbox_app, name="sandbox")
registry_app.add_typer(models_app, name="models")

# ── Auth subgroup ────────────────────────────────────────
app.add_typer(auth_app, name="auth")

# ── Primary user workflows (root) ─────────────────────────
register_config(app)
register_scan(app)
register_uninstall(app)
register_use(app)

# ── Agent pull (full-featured, lives under `observal agent pull`) ──
register_pull(agent_app)

# ── Subgroups ─────────────────────────────────────────────
app.add_typer(registry_app, name="registry")
app.add_typer(agent_app, name="agent")
app.add_typer(mcp_app, name="mcp")
app.add_typer(skill_app, name="skill")
app.add_typer(prompt_app, name="prompt")
app.add_typer(sandbox_app, name="sandbox")
app.add_typer(component_app, name="component")
app.add_typer(ops_app, name="ops")
app.add_typer(admin_app, name="admin")
app.add_typer(self_app, name="self")
app.add_typer(doctor_app, name="doctor")
app.add_typer(support_app, name="support")
app.add_typer(migrate_app, name="migrate")

# Server management (embedded + Docker)
try:
    from observal_cli.cmd_server import server_app

    app.add_typer(server_app, name="server")
except ImportError:
    pass  # server deps not installed


def _show_update_banner() -> None:
    """Post-command hook: show update notification if available.

    Only on interactive TTY, never during self/server commands, never in CI.
    If connected to a server (enterprise): targets the server's version.
    Otherwise: targets the latest GitHub release.
    """
    import sys as _sys

    if not (_sys.stdout.isatty() and _sys.stderr.isatty()):
        return
    if len(_sys.argv) > 1 and _sys.argv[1] in ("self", "server"):
        return
    if os.environ.get("CI") or os.environ.get("OBSERVAL_NO_UPDATE_CHECK"):
        return

    try:
        from observal_cli.version_check import maybe_check

        update = maybe_check()
        if not update:
            return

        from rich import print as _rprint

        if update.source == "server":
            if update.direction == "downgrade":
                _rprint(
                    f"\n[yellow]Your server recommends v{update.latest}. "
                    f"Downgrade: [bold]observal self downgrade --version {update.latest}[/bold][/yellow]"
                )
            else:
                _rprint(
                    f"\n[dim]Your server is v{update.latest}. "
                    f"Match it: [bold]observal self upgrade --version {update.latest}[/bold][/dim]"
                )
        else:
            _rprint(
                f"\n[dim]Update available: v{update.current} \u2192 "
                f"[green]v{update.latest}[/green] \u2022 "
                f"[bold]observal self upgrade[/bold][/dim]"
            )
    except Exception:
        pass  # Never crash the CLI for a version check


# Register update banner as atexit handler so it runs via any entry point
atexit.register(_show_update_banner)

if __name__ == "__main__":
    app()
