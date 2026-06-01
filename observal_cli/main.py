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
    from observal_cli.optic import setup_optic

    setup_optic(debug=debug, verbose=verbose)

    if debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    elif verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Auto-update on minor/patch releases (non-blocking, exempt self/server commands)
    _try_auto_update()


def _try_auto_update() -> None:
    """Attempt auto-update for minor/patch releases on startup.

    Runs silently. Logs a message on success so the user knows the next
    invocation will use the new version.
    Exempt: self/server subcommands, CI, non-TTY.
    """
    # Skip exempt subcommands (check positional args, not flags)
    positional_args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if positional_args and positional_args[0] in ("self", "server"):
        return
    if os.environ.get("CI") or os.environ.get("OBSERVAL_NO_UPDATE_CHECK"):
        return
    if not sys.stdout.isatty():
        return  # Never auto-update in non-interactive environments

    try:
        from observal_cli.version_check import auto_update_if_needed

        if auto_update_if_needed():
            from rich import print as _rprint

            _rprint("[dim]Updated. The new version will be used on your next command.[/dim]")
    except Exception:
        pass  # Never crash the CLI for auto-update


# ── Register command groups ──────────────────────────────

from observal_cli.cmd_agent import agent_app
from observal_cli.cmd_auth import auth_app, register_config
from observal_cli.cmd_co_authors import co_authors_app
from observal_cli.cmd_component import version_app
from observal_cli.cmd_doctor import doctor_app
from observal_cli.cmd_hook import hook_app
from observal_cli.cmd_logs import logs_app
from observal_cli.cmd_mcp import mcp_app
from observal_cli.cmd_migrate import migrate_app
from observal_cli.cmd_models import models_app
from observal_cli.cmd_ops import (
    admin_app,
    ops_app,
    self_app,
)
from observal_cli.cmd_prompt import prompt_app
from observal_cli.cmd_pull import register_pull
from observal_cli.cmd_sandbox import sandbox_app
from observal_cli.cmd_scan import register_scan
from observal_cli.cmd_skill import skill_app
from observal_cli.cmd_support import support_app
from observal_cli.cmd_uninstall import register_uninstall

# ═══════════════════════════════════════════════════════════
# registry_app: Component registry parent group
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
registry_app.add_typer(version_app, name="version")

# ── Auth subgroup ────────────────────────────────────────
app.add_typer(auth_app, name="auth")

# ── Primary user workflows (root) ─────────────────────────
register_config(app)
register_scan(app)


# ── Agent pull (full-featured, lives under `observal agent pull`) ──
register_pull(agent_app)

# ── Subgroups ─────────────────────────────────────────────
app.add_typer(registry_app, name="registry")
app.add_typer(agent_app, name="agent")
app.add_typer(ops_app, name="ops")
app.add_typer(admin_app, name="admin")
app.add_typer(self_app, name="self")
app.add_typer(doctor_app, name="doctor")
app.add_typer(co_authors_app, name="co-authors")

# ── Nest under parent groups ──────────────────────────────
# logs → ops logs (dev log viewer, complements traces/telemetry)
ops_app.add_typer(logs_app, name="logs")
# support → doctor support (diagnostic bundles, related to doctor troubleshooting)
doctor_app.add_typer(support_app, name="support")
# uninstall → self uninstall (CLI lifecycle alongside upgrade/downgrade/rollback)
register_uninstall(self_app)
# migrate → server migrate (operator infra tooling)

# Server management (embedded + Docker)
try:
    from observal_cli.cmd_server import server_app

    server_app.add_typer(migrate_app, name="migrate")
    app.add_typer(server_app, name="server")
except ImportError:
    # server deps not installed; register migrate at top level as fallback
    app.add_typer(migrate_app, name="migrate")


def _show_update_banner() -> None:
    """Post-command hook: show major version notification only.

    Minor/patch mismatches are handled by auto-update.
    Major.minor mismatches are hard-blocked by the version enforcement gate.
    This banner only fires for major upgrades available in community mode.
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

        from packaging.version import Version
        from rich import print as _rprint

        # Only show banner for major version upgrades (community mode)
        # Hard block already handles minor mismatches; auto-update handles patches
        if update.source == "github":
            current_v = Version(update.current)
            latest_v = Version(update.latest)
            if latest_v.major > current_v.major:
                _rprint(
                    f"\n[yellow]Major update available: v{update.current} \u2192 v{update.latest}[/yellow]\n"
                    f"  Run: [bold cyan]observal self upgrade --version {update.latest}[/bold cyan]"
                )
    except Exception:
        pass  # Never crash the CLI for a version check


# Register update banner as atexit handler so it runs via any entry point
atexit.register(_show_update_banner)

if __name__ == "__main__":
    app()
