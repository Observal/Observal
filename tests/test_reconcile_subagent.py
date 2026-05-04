"""Tests for subagent JSONL file discovery and parsing in the reconcile system."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── CLI: _find_recent_sessions ──────────────────────────────────────────────


def test_find_recent_sessions_includes_subagent_files(tmp_path):
    """_find_recent_sessions discovers subagent JSONL files under */subagents/."""
    from observal_cli.cmd_reconcile import _find_recent_sessions

    # Build a fake ~/.claude/projects structure
    project_dir = tmp_path / "project-abc"
    project_dir.mkdir()

    # Top-level session file
    session_id = "abc123"
    top_level = project_dir / f"{session_id}.jsonl"
    top_level.write_text('{"type":"assistant"}\n')

    # Subagent directory structure
    session_subdir = project_dir / session_id
    subagent_dir = session_subdir / "subagents"
    subagent_dir.mkdir(parents=True)
    subagent_file = subagent_dir / "agent-a55579c8.jsonl"
    subagent_file.write_text('{"type":"assistant"}\n')

    with patch("observal_cli.cmd_reconcile._find_claude_sessions_dir", return_value=tmp_path):
        results = _find_recent_sessions(since_hours=168)

    paths = [p for p, _ in results]
    assert top_level in paths, "Top-level session file should be discovered"
    assert subagent_file in paths, "Subagent JSONL file should be discovered"


def test_find_recent_sessions_respects_cutoff_for_subagents(tmp_path):
    """Old subagent files outside the time window are excluded."""
    from observal_cli.cmd_reconcile import _find_recent_sessions

    project_dir = tmp_path / "project-xyz"
    project_dir.mkdir()

    session_id = "old-session"
    session_subdir = project_dir / session_id
    subagent_dir = session_subdir / "subagents"
    subagent_dir.mkdir(parents=True)
    old_subagent = subagent_dir / "agent-old.jsonl"
    old_subagent.write_text('{"type":"assistant"}\n')

    # Set mtime to 30 days ago
    old_time = time.time() - (30 * 24 * 3600)
    import os

    os.utime(old_subagent, (old_time, old_time))

    with patch("observal_cli.cmd_reconcile._find_claude_sessions_dir", return_value=tmp_path):
        results = _find_recent_sessions(since_hours=168)

    paths = [p for p, _ in results]
    assert old_subagent not in paths, "Old subagent file should be excluded"


def test_find_recent_sessions_no_subagents_is_fine(tmp_path):
    """Sessions without subagent directories still work."""
    from observal_cli.cmd_reconcile import _find_recent_sessions

    project_dir = tmp_path / "project-plain"
    project_dir.mkdir()

    top_level = project_dir / "session-plain.jsonl"
    top_level.write_text('{"type":"assistant"}\n')

    with patch("observal_cli.cmd_reconcile._find_claude_sessions_dir", return_value=tmp_path):
        results = _find_recent_sessions(since_hours=168)

    paths = [p for p, _ in results]
    assert top_level in paths


# ─── CLI: _find_session_file ─────────────────────────────────────────────────


def test_find_session_file_finds_subagent(tmp_path):
    """_find_session_file finds agent-<id>.jsonl files inside subagent dirs."""
    from observal_cli.cmd_reconcile import _find_session_file

    project_dir = tmp_path / "project-abc"
    session_id = "parent-session-id"
    subagent_dir = project_dir / session_id / "subagents"
    subagent_dir.mkdir(parents=True)
    subagent_file = subagent_dir / "agent-a55579c8.jsonl"
    subagent_file.write_text('{"type":"assistant"}\n')

    with patch("observal_cli.cmd_reconcile._find_claude_sessions_dir", return_value=tmp_path):
        result = _find_session_file("agent-a55579c8")

    assert result == subagent_file


def test_find_session_file_still_finds_top_level(tmp_path):
    """_find_session_file still finds normal top-level session files."""
    from observal_cli.cmd_reconcile import _find_session_file

    project_dir = tmp_path / "project-abc"
    project_dir.mkdir()
    session_file = project_dir / "normal-session-id.jsonl"
    session_file.write_text('{"type":"assistant"}\n')

    with patch("observal_cli.cmd_reconcile._find_claude_sessions_dir", return_value=tmp_path):
        result = _find_session_file("normal-session-id")

    assert result == session_file


def test_find_session_file_returns_none_when_missing(tmp_path):
    """_find_session_file returns None when the file does not exist."""
    from observal_cli.cmd_reconcile import _find_session_file

    (tmp_path / "project-empty").mkdir()

    with patch("observal_cli.cmd_reconcile._find_claude_sessions_dir", return_value=tmp_path):
        result = _find_session_file("nonexistent-agent-id")

    assert result is None


# ─── CLI: _parse_session_file subagent attribution ───────────────────────────


def test_parse_session_file_detects_subagent_path(tmp_path):
    """_parse_session_file sets is_subagent=True when path is under subagents/."""
    from observal_cli.cmd_reconcile import _parse_session_file

    parent_session_id = "parent-session-abc"
    subagent_dir = tmp_path / parent_session_id / "subagents"
    subagent_dir.mkdir(parents=True)
    subagent_file = subagent_dir / "agent-a55579c8.jsonl"

    record = {
        "type": "assistant",
        "model": "claude-sonnet-4-5",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "message": {"content": []},
    }
    subagent_file.write_text(json.dumps(record) + "\n")

    enrichment = _parse_session_file(subagent_file)

    assert enrichment["is_subagent"] is True
    assert enrichment["parent_session_id"] == parent_session_id
    assert enrichment["subagent_id"] == "agent-a55579c8"


def test_parse_session_file_reads_meta_json(tmp_path):
    """_parse_session_file reads .meta.json for agent_type and agent_description."""
    from observal_cli.cmd_reconcile import _parse_session_file

    subagent_dir = tmp_path / "parent-sess" / "subagents"
    subagent_dir.mkdir(parents=True)
    subagent_file = subagent_dir / "agent-b99.jsonl"
    meta_file = subagent_dir / "agent-b99.meta.json"

    record = {
        "type": "assistant",
        "model": "claude-haiku-4-5",
        "usage": {"input_tokens": 200, "output_tokens": 80},
        "message": {"content": []},
    }
    subagent_file.write_text(json.dumps(record) + "\n")
    meta_file.write_text(
        json.dumps(
            {
                "agentType": "superpowers:code-reviewer",
                "description": "Review PR #472",
            }
        )
    )

    enrichment = _parse_session_file(subagent_file)

    assert enrichment["agent_type"] == "superpowers:code-reviewer"
    assert enrichment["agent_description"] == "Review PR #472"


def test_parse_session_file_meta_json_missing_is_graceful(tmp_path):
    """_parse_session_file handles missing .meta.json without error."""
    from observal_cli.cmd_reconcile import _parse_session_file

    subagent_dir = tmp_path / "parent-sess" / "subagents"
    subagent_dir.mkdir(parents=True)
    subagent_file = subagent_dir / "agent-nometa.jsonl"

    record = {
        "type": "assistant",
        "model": "claude-sonnet-4-5",
        "usage": {"input_tokens": 50, "output_tokens": 30},
        "message": {"content": []},
    }
    subagent_file.write_text(json.dumps(record) + "\n")
    # No .meta.json file created

    enrichment = _parse_session_file(subagent_file)

    assert enrichment["is_subagent"] is True
    assert enrichment["agent_type"] is None
    assert enrichment["agent_description"] is None


def test_parse_session_file_top_level_is_not_subagent(tmp_path):
    """Top-level session files have is_subagent=False and no subagent fields."""
    from observal_cli.cmd_reconcile import _parse_session_file

    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    session_file = project_dir / "top-level-session.jsonl"

    record = {
        "type": "assistant",
        "model": "claude-sonnet-4-5",
        "usage": {"input_tokens": 300, "output_tokens": 100},
        "message": {"content": []},
    }
    session_file.write_text(json.dumps(record) + "\n")

    enrichment = _parse_session_file(session_file)

    assert enrichment["is_subagent"] is False
    assert enrichment["parent_session_id"] is None
    assert enrichment.get("subagent_id") is None


def test_parse_session_file_subagent_uses_filename_as_dedup_key(tmp_path):
    """subagent_id is the stem of the file, not the session_id in the JSONL."""
    from observal_cli.cmd_reconcile import _parse_session_file

    parent_session_id = "shared-parent-session"
    subagent_dir = tmp_path / parent_session_id / "subagents"
    subagent_dir.mkdir(parents=True)
    subagent_file = subagent_dir / "agent-unique-stem.jsonl"

    # The JSONL session_id is the parent's — but subagent_id should be the filename stem
    record = {
        "type": "assistant",
        "sessionId": parent_session_id,  # This is the parent session ID in the JSONL
        "model": "claude-sonnet-4-5",
        "usage": {"input_tokens": 100, "output_tokens": 40},
        "message": {"content": []},
    }
    subagent_file.write_text(json.dumps(record) + "\n")

    enrichment = _parse_session_file(subagent_file)

    assert enrichment["subagent_id"] == "agent-unique-stem"


# ─── Server: ReconcilePayload accepts subagent fields ────────────────────────


def test_reconcile_payload_accepts_subagent_fields():
    """ReconcilePayload accepts the new subagent attribution fields."""
    from api.routes.reconcile import ReconcilePayload

    payload = ReconcilePayload(
        session_id="parent-session-abc",
        is_subagent=True,
        parent_session_id="parent-session-abc",
        subagent_id="agent-a55579c8",
        agent_type="superpowers:code-reviewer",
        agent_description="Review PR #472",
    )

    assert payload.is_subagent is True
    assert payload.subagent_id == "agent-a55579c8"
    assert payload.agent_type == "superpowers:code-reviewer"


def test_reconcile_payload_defaults_are_not_subagent():
    """ReconcilePayload defaults to is_subagent=False (backward-compatible)."""
    from api.routes.reconcile import ReconcilePayload

    payload = ReconcilePayload(session_id="some-session")

    assert payload.is_subagent is False
    assert payload.parent_session_id is None
    assert payload.subagent_id is None
    assert payload.agent_type is None
    assert payload.agent_description is None


# ─── Server: reconcile endpoint subagent dedup key ───────────────────────────


@pytest.mark.asyncio
async def test_reconcile_endpoint_uses_subagent_id_for_dedup():
    """When is_subagent=True, the dedup check uses subagent_id, not session_id."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from api.routes.reconcile import router

    app = FastAPI()
    app.include_router(router)

    session_exists_resp = MagicMock()
    session_exists_resp.raise_for_status = MagicMock()
    session_exists_resp.json = MagicMock(return_value={"data": [{"cnt": "5"}]})

    not_reconciled_resp = MagicMock()
    not_reconciled_resp.raise_for_status = MagicMock()
    not_reconciled_resp.json = MagicMock(return_value={"data": [{"cnt": "0"}]})

    payload = {
        "session_id": "parent-session",
        "is_subagent": True,
        "parent_session_id": "parent-session",
        "subagent_id": "agent-unique-stem",
        "agent_type": "superpowers:code-reviewer",
        "agent_description": "Review PR #472",
        "conversation_turns": 3,
    }

    inserted_rows = []

    async def mock_insert(rows):
        inserted_rows.extend(rows)

    with (
        patch(
            "api.routes.reconcile._query",
            new_callable=AsyncMock,
            side_effect=[session_exists_resp, not_reconciled_resp],
        ),
        patch("api.routes.reconcile.insert_otel_logs", side_effect=mock_insert),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/telemetry/reconcile", json=payload)

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "reconciled"

    # The enrichment row should store the subagent_id for dedup purposes
    enrichment_rows = [row for row in inserted_rows if row["LogAttributes"].get("event.name") == "reconcile_enrichment"]
    assert len(enrichment_rows) == 1
    attrs = enrichment_rows[0]["LogAttributes"]
    assert attrs.get("subagent_id") == "agent-unique-stem"
    assert attrs.get("is_subagent") == "true"
    assert attrs.get("agent_type") == "superpowers:code-reviewer"


@pytest.mark.asyncio
async def test_reconcile_endpoint_subagent_dedup_uses_subagent_id_not_session_id():
    """Already-reconciled check for subagents queries by subagent_id, not session_id."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from api.routes.reconcile import router

    app = FastAPI()
    app.include_router(router)

    session_exists_resp = MagicMock()
    session_exists_resp.raise_for_status = MagicMock()
    session_exists_resp.json = MagicMock(return_value={"data": [{"cnt": "5"}]})

    # Subagent is already reconciled
    already_reconciled_resp = MagicMock()
    already_reconciled_resp.raise_for_status = MagicMock()
    already_reconciled_resp.json = MagicMock(return_value={"data": [{"cnt": "1"}]})

    payload = {
        "session_id": "parent-session",
        "is_subagent": True,
        "subagent_id": "agent-already-done",
        "conversation_turns": 3,
    }

    with patch(
        "api.routes.reconcile._query",
        new_callable=AsyncMock,
        side_effect=[session_exists_resp, already_reconciled_resp],
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/telemetry/reconcile", json=payload)

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "skipped"


# ─── Server: SessionEnrichment dataclass ────────────────────────────────────


def test_session_enrichment_has_subagent_fields():
    """SessionEnrichment dataclass includes the new subagent attribution fields."""
    from services.insights.reconcile import SessionEnrichment

    e = SessionEnrichment(session_id="parent-abc")
    assert hasattr(e, "is_subagent")
    assert e.is_subagent is False
    assert hasattr(e, "parent_session_id")
    assert e.parent_session_id is None
    assert hasattr(e, "subagent_id")
    assert e.subagent_id is None
    assert hasattr(e, "agent_type")
    assert e.agent_type is None
    assert hasattr(e, "agent_description")
    assert e.agent_description is None


def test_enrichment_to_dict_includes_subagent_fields():
    """enrichment_to_dict includes the subagent fields in serialised output."""
    from services.insights.reconcile import SessionEnrichment, enrichment_to_dict

    e = SessionEnrichment(
        session_id="parent-abc",
        is_subagent=True,
        parent_session_id="parent-abc",
        subagent_id="agent-xyz",
        agent_type="superpowers:tdd",
        agent_description="Write tests",
    )
    d = enrichment_to_dict(e)

    assert d["is_subagent"] is True
    assert d["subagent_id"] == "agent-xyz"
    assert d["agent_type"] == "superpowers:tdd"
    assert d["agent_description"] == "Write tests"


# ─── CLI: batch reconcile counts subagents ───────────────────────────────────


def test_find_recent_sessions_counts_are_separated(tmp_path):
    """Both top-level and subagent files are returned; caller can count each type."""
    from observal_cli.cmd_reconcile import _find_recent_sessions

    project_dir = tmp_path / "project-mixed"
    project_dir.mkdir()

    # 2 top-level sessions
    (project_dir / "sess-1.jsonl").write_text("{}\n")
    (project_dir / "sess-2.jsonl").write_text("{}\n")

    # 1 session with 3 subagents
    sess_dir = project_dir / "sess-1"
    subagent_dir = sess_dir / "subagents"
    subagent_dir.mkdir(parents=True)
    (subagent_dir / "agent-a.jsonl").write_text("{}\n")
    (subagent_dir / "agent-b.jsonl").write_text("{}\n")
    (subagent_dir / "agent-c.jsonl").write_text("{}\n")

    with patch("observal_cli.cmd_reconcile._find_claude_sessions_dir", return_value=tmp_path):
        results = _find_recent_sessions(since_hours=168)

    paths = [p for p, _ in results]
    subagent_paths = [p for p in paths if p.parent.name == "subagents"]
    top_level_paths = [p for p in paths if p.parent.name != "subagents"]

    assert len(top_level_paths) == 2
    assert len(subagent_paths) == 3
