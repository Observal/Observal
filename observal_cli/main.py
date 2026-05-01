"""Observal CLI: MCP Server & Agent Registry."""

import logging

import typer

from observal_cli.cmd_auth import version_callback

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
from observal_cli.cmd_doctor import doctor_app
from observal_cli.cmd_hook import hook_app
from observal_cli.cmd_mcp import mcp_app
from observal_cli.cmd_migrate import migrate_app
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
app.add_typer(ops_app, name="ops")
app.add_typer(admin_app, name="admin")
app.add_typer(self_app, name="self")
app.add_typer(doctor_app, name="doctor")
app.add_typer(migrate_app, name="migrate")


if __name__ == "__main__":
    app()
