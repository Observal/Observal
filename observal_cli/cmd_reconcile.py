"""observal reconcile — Parse local session files and send enrichment to server.

Usage:
    observal reconcile <session-id>         Parse specific session JSONL
    observal reconcile --latest             Parse most recent session
    observal reconcile --all --since 7d     Parse all sessions from last 7 days
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import httpx
import typer
from rich import print as rprint
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from observal_cli import config

logger = logging.getLogger(__name__)

reconcile_app = typer.Typer(
    name="reconcile",
    help="Parse local IDE session files and enrich server telemetry.",
    no_args_is_help=True,
)


def _find_claude_sessions_dir() -> Path | None:
    """Find the Claude Code projects directory."""
    claude_dir = Path.home() / ".claude" / "projects"
    if claude_dir.exists():
        return claude_dir
    return None


def _find_session_file(session_id: str) -> Path | None:
    """Find a specific session or subagent JSONL file by ID."""
    claude_dir = _find_claude_sessions_dir()
    if not claude_dir:
        return None

    for project_dir in claude_dir.iterdir():
        if not project_dir.is_dir():
            continue
        # Top-level sessions: ~/.claude/projects/<project>/<session-id>.jsonl
        session_file = project_dir / f"{session_id}.jsonl"
        if session_file.exists():
            return session_file
        # Subagent sessions: ~/.claude/projects/<project>/<session-id>/subagents/<id>.jsonl
        for session_dir in project_dir.iterdir():
            if not session_dir.is_dir():
                continue
            subagent_file = session_dir / "subagents" / f"{session_id}.jsonl"
            if subagent_file.exists():
                return subagent_file

    return None


def _find_recent_sessions(since_hours: float = 168) -> list[tuple[Path, float]]:
    """Find all session JSONL files modified within the given timeframe.

    Discovers both top-level sessions AND subagent files within session directories.
    """
    claude_dir = _find_claude_sessions_dir()
    if not claude_dir:
        return []

    cutoff = time.time() - (since_hours * 3600)
    sessions = []

    for project_dir in claude_dir.iterdir():
        if not project_dir.is_dir():
            continue
        # Top-level sessions
        for f in project_dir.glob("*.jsonl"):
            mtime = f.stat().st_mtime
            if mtime >= cutoff:
                sessions.append((f, mtime))
        # Subagent sessions: <project>/<session-id>/subagents/*.jsonl
        for session_dir in project_dir.iterdir():
            if not session_dir.is_dir():
                continue
            subagent_dir = session_dir / "subagents"
            if subagent_dir.exists():
                for f in subagent_dir.glob("*.jsonl"):
                    mtime = f.stat().st_mtime
                    if mtime >= cutoff:
                        sessions.append((f, mtime))

    # Sort by most recent first
    sessions.sort(key=lambda x: x[1], reverse=True)
    return sessions


def _parse_session_file(path: Path) -> dict:
    """Parse a Claude Code session JSONL file into enrichment data.

    Captures ALL records from the JSONL: assistant turns (with full content),
    user messages, system prompts, tool results, attachments — everything.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    session_id = path.stem  # filename without .jsonl

    enrichment = {
        "session_id": session_id,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_read_tokens": 0,
        "total_cache_creation_tokens": 0,
        "models_used": [],
        "primary_model": None,
        "total_cost_usd": 0.0,
        "service_tier": None,
        "conversation_turns": 0,
        "tool_use_count": 0,
        "thinking_turns": 0,
        "stop_reasons": {},
        "completeness_score": 1.0,
        "per_turn": [],
        "records": [],
        # Subagent attribution
        "is_subagent": False,
        "parent_session_id": None,
        "subagent_id": None,
        "agent_type": None,
        "agent_description": None,
    }

    # Detect subagent files: path.parent.name == "subagents"
    if path.parent.name == "subagents":
        enrichment["is_subagent"] = True
        enrichment["parent_session_id"] = path.parent.parent.name
        enrichment["subagent_id"] = path.stem

        meta_path = path.with_suffix(".meta.json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                enrichment["agent_type"] = meta.get("agentType")
                enrichment["agent_description"] = meta.get("description")
            except (json.JSONDecodeError, OSError):
                pass

    models_seen: set[str] = set()
    turn_index = 0
    service_tier = None
    seq = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        record_type = record.get("type", "")
        seq += 1

        # Only send content types — server discards everything else anyway.
        # This reduces payload size significantly (metadata types add bulk).
        if record_type in ("assistant", "user", "system"):
            enrichment["records"].append(record)

        # Aggregate stats from assistant records
        if record_type == "assistant":
            turn_index += 1
            message = record.get("message", {})
            usage = message.get("usage", {}) or record.get("usage", {})
            content = message.get("content", [])

            model = record.get("model") or message.get("model")
            stop_reason = record.get("stop_reason") or message.get("stop_reason")
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            cache_creation = usage.get("cache_creation_input_tokens", 0)
            service_tier = usage.get("service_tier") or service_tier

            has_thinking = False
            tool_uses = []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "thinking":
                            has_thinking = True
                        elif block.get("type") == "tool_use":
                            tool_uses.append(block.get("name", "unknown"))

            enrichment["total_input_tokens"] += input_tokens
            enrichment["total_output_tokens"] += output_tokens
            enrichment["total_cache_read_tokens"] += cache_read
            enrichment["total_cache_creation_tokens"] += cache_creation
            enrichment["tool_use_count"] += len(tool_uses)

            if model:
                models_seen.add(model)
            if has_thinking:
                enrichment["thinking_turns"] += 1
            if stop_reason:
                enrichment["stop_reasons"][stop_reason] = enrichment["stop_reasons"].get(stop_reason, 0) + 1

    enrichment["conversation_turns"] = turn_index
    enrichment["models_used"] = sorted(models_seen)
    enrichment["primary_model"] = enrichment["models_used"][0] if enrichment["models_used"] else None
    enrichment["service_tier"] = service_tier

    return enrichment


def _send_enrichment(server_url: str, headers: dict, enrichment: dict) -> dict:
    """POST enrichment data to the reconcile endpoint."""
    url = f"{server_url}/api/v1/telemetry/reconcile"
    try:
        resp = httpx.post(url, json=enrichment, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return {"status": "error", "reason": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


@reconcile_app.command("session")
def reconcile_session(
    session_id: str = typer.Argument(help="Session ID to reconcile (or 'latest')"),
):
    """Parse a specific session JSONL file and send enrichment to server."""
    cfg = config.get_or_exit()
    server_url = cfg["server_url"].rstrip("/")
    headers = {"Authorization": f"Bearer {cfg['access_token']}"}

    if session_id == "latest":
        sessions = _find_recent_sessions(since_hours=24)
        if not sessions:
            rprint("[red]No recent sessions found in ~/.claude/projects/[/red]")
            raise typer.Exit(1)
        path = sessions[0][0]
        session_id = path.stem
        rprint(f"[dim]Using latest session: {session_id}[/dim]")
    else:
        path = _find_session_file(session_id)
        if not path:
            rprint(f"[red]Session file not found for: {session_id}[/red]")
            rprint("[dim]Looked in ~/.claude/projects/*/[/dim]")
            raise typer.Exit(1)

    rprint(f"[dim]Parsing: {path}[/dim]")
    enrichment = _parse_session_file(path)

    if enrichment["conversation_turns"] == 0:
        rprint("[yellow]No assistant turns found in session file.[/yellow]")
        raise typer.Exit(0)

    # Show summary
    table = Table(title="Session Enrichment Summary")
    table.add_column("Metric", style="dim")
    table.add_column("Value", style="bold")
    if enrichment.get("is_subagent"):
        table.add_row("Type", "Subagent")
        table.add_row("Agent Type", enrichment.get("agent_type") or "unknown")
        parent = enrichment["parent_session_id"] or ""
        table.add_row("Parent Session", parent[:16] + "..." if len(parent) > 16 else parent)
    table.add_row("Turns", str(enrichment["conversation_turns"]))
    table.add_row("Model", enrichment["primary_model"] or "unknown")
    table.add_row("Input Tokens", f"{enrichment['total_input_tokens']:,}")
    table.add_row("Output Tokens", f"{enrichment['total_output_tokens']:,}")
    table.add_row("Cache Read", f"{enrichment['total_cache_read_tokens']:,}")
    table.add_row("Cache Creation", f"{enrichment['total_cache_creation_tokens']:,}")
    table.add_row("Tool Uses", str(enrichment["tool_use_count"]))
    table.add_row("Thinking Turns", str(enrichment["thinking_turns"]))
    rprint(table)

    # Send to server
    rprint("\n[dim]Sending to server...[/dim]")
    result = _send_enrichment(server_url, headers, enrichment)

    if result.get("status") == "reconciled":
        rprint(f"[green]✓ Reconciled successfully[/green] — cost: ${result.get('total_cost_usd', 0):.4f}")
    elif result.get("status") == "skipped":
        rprint(f"[yellow]⊘ Skipped: {result.get('reason')}[/yellow]")
    else:
        rprint(f"[red]✗ Error: {result.get('reason')}[/red]")


@reconcile_app.command("batch")
def reconcile_batch(
    since: str = typer.Option("7d", help="Time window: 1d, 7d, 30d"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be reconciled"),
):
    """Reconcile all recent sessions in batch."""
    hours_map = {"1d": 24, "7d": 168, "14d": 336, "30d": 720}
    hours = hours_map.get(since, 168)

    sessions = _find_recent_sessions(since_hours=hours)
    if not sessions:
        rprint(f"[yellow]No sessions found in the last {since}[/yellow]")
        raise typer.Exit(0)

    subagent_count = sum(1 for p, _ in sessions if p.parent.name == "subagents")
    main_count = len(sessions) - subagent_count
    rprint(
        f"[dim]Found {len(sessions)} files in the last {since} ({main_count} sessions, {subagent_count} subagents)[/dim]\n"
    )

    if dry_run:
        table = Table(title="Sessions to Reconcile")
        table.add_column("Session ID", style="dim")
        table.add_column("Modified", style="dim")
        table.add_column("Size", style="dim")
        for path, mtime in sessions[:20]:
            modified = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            size = f"{path.stat().st_size / 1024:.0f}KB"
            table.add_row(path.stem[:16] + "...", modified, size)
        if len(sessions) > 20:
            table.add_row(f"... and {len(sessions) - 20} more", "", "")
        rprint(table)
        return

    cfg = config.get_or_exit()
    server_url = cfg["server_url"].rstrip("/")
    headers = {"Authorization": f"Bearer {cfg['access_token']}"}

    reconciled = 0
    skipped = 0
    errors = 0

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Reconciling...", total=len(sessions))
        for path, _ in sessions:
            progress.update(task, description=f"Processing {path.stem[:16]}...")
            try:
                enrichment = _parse_session_file(path)
                if enrichment["conversation_turns"] == 0:
                    skipped += 1
                    continue
                result = _send_enrichment(server_url, headers, enrichment)
                if result.get("status") == "reconciled":
                    reconciled += 1
                elif result.get("status") == "skipped":
                    skipped += 1
                else:
                    errors += 1
            except Exception as e:
                logger.debug(f"Error processing {path}: {e}")
                errors += 1
            progress.advance(task)

    rprint(
        f"\n[green]✓ Reconciled: {reconciled}[/green]  [yellow]⊘ Skipped: {skipped}[/yellow]  [red]✗ Errors: {errors}[/red]"
    )
