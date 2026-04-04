"""Observal CLI: MCP Server & Agent Registry."""

import typer

app = typer.Typer(
    name="observal",
    help="Observal: MCP Server & Agent Registry CLI",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)

# ── Register command groups ──────────────────────────────

from observal_cli.cmd_agent import agent_app
from observal_cli.cmd_auth import register_auth, register_config
from observal_cli.cmd_graphrag import register_graphrag
from observal_cli.cmd_hook import register_hook
from observal_cli.cmd_mcp import register_mcp
from observal_cli.cmd_ops import (
    admin_app,
    eval_app,
    register_dashboard,
    register_feedback,
    register_lifecycle,
    register_traces,
    review_app,
    telemetry_app,
)
from observal_cli.cmd_prompt import register_prompt
from observal_cli.cmd_sandbox import register_sandbox
from observal_cli.cmd_skill import register_skill
from observal_cli.cmd_tool import register_tool

register_auth(app)
register_config(app)
register_mcp(app)
register_dashboard(app)
register_feedback(app)
register_traces(app)
register_lifecycle(app)
register_tool(app)
register_skill(app)
register_hook(app)
register_prompt(app)
register_sandbox(app)
register_graphrag(app)

app.add_typer(agent_app, name="agent")
app.add_typer(review_app, name="review")
app.add_typer(telemetry_app, name="telemetry")
app.add_typer(eval_app, name="eval")
app.add_typer(admin_app, name="admin")


if __name__ == "__main__":
    app()
