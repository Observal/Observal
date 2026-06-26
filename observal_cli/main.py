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

_shared = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "packages", "observal-shared"))
if os.path.isdir(_shared) and _shared not in sys.path:
    sys.path.insert(0, _shared)

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

    # One-time migration: .observal/agent markers → lockfile.json
    _try_lockfile_migration()


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


def _try_lockfile_migration() -> None:
    """One-time migration of .observal/agent markers to lockfile.json.

    Runs only when: lockfile.json doesn't exist but config.json DOES
    (meaning the user has previously logged in but never had a lockfile).
    Skips entirely if ~/.observal/ doesn't exist yet (fresh install).
    """
    try:
        from observal_cli.lockfile import CONFIG_DIR, LOCKFILE_PATH, migrate_agent_markers

        # Don't run if the config dir doesn't exist yet (auth login hasn't happened)
        if not CONFIG_DIR.exists():
            return
        if not LOCKFILE_PATH.exists():
            migrate_agent_markers()
    except Exception:
        pass  # Never crash the CLI for migration


# ── Register command groups ──────────────────────────────

from observal_cli.cmd_agent import agent_app
from observal_cli.cmd_archive import add_archive_commands
from observal_cli.cmd_auth import auth_app, register_config
from observal_cli.cmd_co_authors import make_co_authors_typer
from observal_cli.cmd_component import version_app
from observal_cli.cmd_doctor import doctor_app
from observal_cli.cmd_hook import hook_app
from observal_cli.cmd_insights import insights_app
from observal_cli.cmd_logs import logs_app
from observal_cli.cmd_mcp import mcp_app
from observal_cli.cmd_migrate import migrate_app
from observal_cli.cmd_models import models_app
from observal_cli.cmd_ops import (
    admin_app,
    ops_app,
    self_app,
)
from observal_cli.cmd_outdated import register_outdated
from observal_cli.cmd_prompt import prompt_app
from observal_cli.cmd_pull import register_pull
from observal_cli.cmd_sandbox import sandbox_app
from observal_cli.cmd_scan import register_scan
from observal_cli.cmd_skill import skill_app
from observal_cli.cmd_support import support_app
from observal_cli.cmd_transfer import add_transfer_owner_command
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

# ── Co-authors and ownership sub-commands ─────────────────
mcp_app.add_typer(make_co_authors_typer("mcps"), name="co-authors")
skill_app.add_typer(make_co_authors_typer("skills"), name="co-authors")
hook_app.add_typer(make_co_authors_typer("hooks"), name="co-authors")
prompt_app.add_typer(make_co_authors_typer("prompts"), name="co-authors")
sandbox_app.add_typer(make_co_authors_typer("sandboxes"), name="co-authors")
agent_app.add_typer(make_co_authors_typer("agents"), name="co-authors")
add_transfer_owner_command(mcp_app, "mcps")
add_transfer_owner_command(skill_app, "skills")
add_transfer_owner_command(hook_app, "hooks")
add_transfer_owner_command(prompt_app, "prompts")
add_transfer_owner_command(sandbox_app, "sandboxes")
add_transfer_owner_command(agent_app, "agents")
add_archive_commands(mcp_app, "mcps")
add_archive_commands(skill_app, "skills")
add_archive_commands(hook_app, "hooks")
add_archive_commands(prompt_app, "prompts")
add_archive_commands(sandbox_app, "sandboxes")

# ── Auth subgroup ────────────────────────────────────────
app.add_typer(auth_app, name="auth")

# ── Primary user workflows (root) ─────────────────────────
register_config(app)
register_scan(app)
register_outdated(app)


# ── Agent pull (full-featured, lives under `observal agent pull`) ──
register_pull(agent_app)

# ── Subgroups ─────────────────────────────────────────────
app.add_typer(registry_app, name="registry")
app.add_typer(agent_app, name="agent")
app.add_typer(ops_app, name="ops")
app.add_typer(admin_app, name="admin")
app.add_typer(self_app, name="self")
app.add_typer(doctor_app, name="doctor")

# ── Nest under parent groups ──────────────────────────────
# logs → ops logs (dev log viewer, complements traces/telemetry)
ops_app.add_typer(logs_app, name="logs")
# insights → ops insights (agent insight reports)
ops_app.add_typer(insights_app, name="insights")
# support → doctor support (diagnostic bundles, related to doctor troubleshooting)
doctor_app.add_typer(support_app, name="support")
# uninstall → self uninstall (CLI lifecycle alongside upgrade/downgrade/rollback)
register_uninstall(self_app)
# migrate → server migrate (operator infra tooling)

# Reconcile (push local sessions to server)
from observal_cli.cmd_reconcile_cli import reconcile_app

app.add_typer(reconcile_app, name="reconcile")

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
                    f"  Run: [bold cyan]pipx install --force 'observal-cli=={update.latest}'[/bold cyan]"
                )
    except Exception:
        pass  # Never crash the CLI for a version check


# Register update banner as atexit handler so it runs via any entry point
atexit.register(_show_update_banner)

if __name__ == "__main__":
    app()
