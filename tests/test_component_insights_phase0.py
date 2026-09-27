# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi
# SPDX-License-Identifier: Apache-2.0

"""Phase 0 evidence: current behaviour, not a working component attribution feature."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from observal_cli import layer, lockfile
from observal_cli.sessions import base as session_base
from services import session_ingest
from services.config_generator import _build_mcp_context
from services.harness.helpers import _local_registry_names
from services.session_parsers.ingest_classify import get_classifier

FIXTURE = Path(__file__).parent / "fixtures" / "component_insights" / "claude_code"
SOURCE_INDICES = (21, 22, 23, 24, 33, 34, 35, 36, 38, 39)


def _records():
    return [json.loads(line) for line in (FIXTURE / "session.jsonl").read_text().splitlines()]


def _block(record):
    return record["message"]["content"][0]


def test_sanitized_live_derived_fixture_provenance_and_install_state():
    rows = dict(zip(SOURCE_INDICES, _records(), strict=True))
    assert len(rows) == 10
    assert rows[33]["message"]["id"] == rows[34]["message"]["id"]
    assert len({_block(rows[i])["id"] for i in (33, 34)}) == 2
    assert len({rows[i]["message"]["id"] for i in (21, 22, 23)}) == 1
    assert rows[22]["message"]["id"] != rows[33]["message"]["id"]
    assert [_block(rows[i])["type"] for i in (21, 22, 23)] == ["thinking", "text", "tool_use"]
    assert [_block(rows[i])["tool_use_id"] for i in (35, 36, 39)] == [_block(rows[i])["id"] for i in (33, 34, 38)]
    assert "is_error" not in _block(rows[35]) and "is_error" not in _block(rows[36])
    assert _block(rows[39])["is_error"] is True
    assert all(_block(rows[i])["input"] == {} for i in (23, 33, 34, 38))
    assert all(_block(rows[i])["content"] == "[sanitized fixture result]" for i in (24, 35, 36, 39))
    assert all(row["uuid"].startswith("source-fixture-") for row in rows.values())

    agent = json.loads((FIXTURE / "lockfile.json").read_text())["registries"]["https://fixture.invalid"]["harnesses"][
        "claude-code"
    ]["agents"][0]
    assert len(agent["components"]) == 2
    assert len({c["id"] for c in agent["components"]}) == 2
    assert len({c["name"] for c in agent["components"]}) == 1
    registry = json.loads((FIXTURE / "registry_components.json").read_text())["components"]
    assert [c["id"] for c in registry] == [c["id"] for c in agent["components"]]
    assert {c["slug"] for c in registry} == {"phase0-probe"}
    assert len({c["qualified_name"].split("/")[0] for c in registry}) == 2
    aliases = json.loads((FIXTURE / "effective_mcp_config.json").read_text())["mcpServers"]
    assert set(aliases) == {c["installed_alias"] for c in registry}
    assert set(aliases) == {_block(rows[i])["name"].split("__")[1] for i in (33, 34)}
    assert _block(rows[38])["name"].split("__")[1] in aliases
    assert all(_block(rows[i])["name"].startswith("mcp__") for i in (33, 34, 38))
    snap = json.loads((FIXTURE / "pinned_snapshot.json").read_text())
    pinned = snap["pinned_versions"]["agents"][0]
    assert pinned["id"] == agent["id"]
    assert [(c["name"], c["version"]) for c in pinned["components"]] == [
        (c["name"], c["version"]) for c in agent["components"]
    ]
    assert all("id" not in comp for comp in pinned["components"])
    assert snap["pinned_versions"]["standalone"] == []
    entries = [
        (f"{harness}/{item['path']}", item["hash"]) for harness, files in snap["harnesses"].items() for item in files
    ]
    assert snap["hash"] == hashlib.sha256(json.dumps(sorted(entries), sort_keys=True).encode()).hexdigest()[:16]


@pytest.fixture
def ingest_insert(monkeypatch):
    inserted = AsyncMock()
    for name, value in {
        "query_existing_for_dedup": AsyncMock(return_value={}),
        "query_session_checkpoint": AsyncMock(return_value=(-1, 0)),
        "query_session_source_manifest": AsyncMock(return_value=[]),
        "query_source_records_after": AsyncMock(return_value=[]),
        "insert_session_events": inserted,
        "insert_session_checkpoint": AsyncMock(),
        "refresh_session_summary": AsyncMock(),
        "_resolve_agent_id": AsyncMock(side_effect=lambda value: value),
        "_resolve_agent_version": AsyncMock(side_effect=lambda _agent, value: value),
    }.items():
        monkeypatch.setattr(session_ingest, name, value)
    return inserted


@pytest.mark.asyncio
async def test_live_derived_fixture_through_canonical_ingest(ingest_insert):
    inserted = ingest_insert
    source = (FIXTURE / "session.jsonl").read_text().splitlines()
    for start, stop in ((21, 25), (33, 37), (38, 40)):
        selected = [source[SOURCE_INDICES.index(offset)] for offset in range(start, stop)]
        await session_ingest.ingest_session_lines(
            session_id="fixture-session",
            project_id="fixture-project",
            user_id="fixture-user",
            agent_id=None,
            agent_version=None,
            harness="claude-code",
            lines=selected,
            start_offset=start,
        )
    rows = {r["line_offset"]: r for call in inserted.call_args_list for r in call.args[0] if r["is_source_record"]}
    assert set(rows) == set(SOURCE_INDICES)
    assert all(r["rendered"] == 1 for r in rows.values())
    assert [rows[i]["event_type"] for i in SOURCE_INDICES] == [
        "thinking",
        "assistant_text",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_call",
        "tool_result",
        "tool_result",
        "tool_call",
        "tool_result",
    ]
    for index in (23, 33, 34, 38):
        assert rows[index]["tool_name"] == _block(json.loads(rows[index]["raw_line"]))["name"]
        assert rows[index]["tool_id"] == _block(json.loads(rows[index]["raw_line"]))["id"]
    assert len({rows[i]["tool_id"] for i in (33, 34)}) == 2
    assert all(rows[i]["tool_name"] is None for i in (21, 22, 24, 35, 36, 39))
    assert json.loads(rows[33]["raw_line"])["message"]["id"] == json.loads(rows[34]["raw_line"])["message"]["id"]
    assert _block(json.loads(rows[39]["raw_line"]))["is_error"] is True


def test_constructed_single_record_edge_cases_are_not_claimed_as_live():
    classify, _preview, tool_info = get_classifier("claude-code")
    calls = [{"type": "tool_use", "id": f"constructed-{n}", "name": f"mcp__fixture__{n}", "input": {}} for n in (1, 2)]
    multi = {"type": "assistant", "message": {"content": calls}}
    assert classify(multi) == "tool_call"
    assert tool_info(multi) == ("mcp__fixture__1", "constructed-1")
    assert len(json.loads(json.dumps(multi))["message"]["content"]) == 2
    text_first = {"type": "assistant", "message": {"content": [{"type": "text", "text": "[constructed]"}, calls[0]]}}
    assert classify(text_first) == "assistant_text"
    assert tool_info(text_first) == ("mcp__fixture__1", "constructed-1")
    missing_result = {"type": "assistant", "message": {"content": [calls[0]]}}
    assert all(b["type"] != "tool_result" for b in missing_result["message"]["content"])


@pytest.mark.asyncio
async def test_constructed_multiblock_input_keeps_all_blocks_in_source_row(ingest_insert):
    calls = [{"type": "tool_use", "id": f"constructed-{n}", "name": f"mcp__fixture__{n}", "input": {}} for n in (1, 2)]
    multi = {"type": "assistant", "message": {"content": calls}}
    text_first = {"type": "assistant", "message": {"content": [{"type": "text", "text": "[constructed]"}, calls[0]]}}
    await session_ingest.ingest_session_lines(
        session_id="constructed-phase0",
        project_id="fixture-project",
        user_id="fixture-user",
        agent_id=None,
        agent_version=None,
        harness="claude-code",
        lines=[json.dumps(multi), json.dumps(text_first)],
    )
    rows = [r for call in ingest_insert.call_args_list for r in call.args[0] if r["is_source_record"]]
    assert [(row["event_type"], row["tool_name"], row["tool_id"]) for row in rows] == [
        ("tool_call", "mcp__fixture__1", "constructed-1"),
        ("assistant_text", "mcp__fixture__1", "constructed-1"),
    ]
    assert len(json.loads(rows[0]["raw_line"])["message"]["content"]) == 2
    assert json.loads(rows[0]["raw_line"])["message"]["content"][1]["id"] == "constructed-2"
    assert json.loads(rows[1]["raw_line"])["message"]["content"][1]["id"] == "constructed-1"


def test_bundled_alias_disambiguation_and_collisions():
    a, b, c = "first", "second", "third"
    listings = {
        a: SimpleNamespace(slug="probe", namespace="team.a"),
        b: SimpleNamespace(slug="probe", namespace="team-a"),
        c: SimpleNamespace(slug="probe", namespace="else"),
    }
    assert _local_registry_names(listings) == {a: "team-a-probe", b: "team-a-probe-2", c: "else-probe"}
    assert "team-a-probe-2".startswith("team-a-probe")  # Prefix matching must not identify a listing.
    assert len({"project:mcp__alias__ping", "user:mcp__alias__ping"}) == 2  # Scope is part of identity.
    listing = SimpleNamespace(
        slug="probe",
        namespace="team.a",
        environment_variables=[],
        transport="stdio",
        url=None,
        framework=None,
        docker_image=None,
        command="python3",
        args=["fixture.py"],
        auto_approve=[],
    )
    assert _build_mcp_context(listing, local_name="local name").name == "local-name"


def test_current_mcp_drift_flag_does_not_verify_edited_or_removed_entry():
    pinned = {
        "harnesses": {
            "claude-code": {"agents": [{"components": [{"name": "probe", "type": "mcp", "integrity": "expected"}]}]}
        }
    }
    assert layer._integrity_check_paths("claude-code", "mcp", "probe") == []
    for files in ([], [{"path": "project:.claude.json", "hash": "edited"}]):
        assert layer._compute_drift(pinned, {"claude-code": files}) == {"is_canonical": True, "drifted_files": []}


def test_cached_first_session_layer_hash_hides_mid_session_change(monkeypatch):
    values = iter(("old-file-hash", "new-file-hash"))
    calls = []

    def calculate(cwd, harness):
        calls.append((cwd, harness))
        return next(values)

    monkeypatch.setattr(session_base, "_compute_layer_hash_safe", calculate)
    sid = "fixture-phase0-session"
    session_base._evict_layer_hash_cache(sid)
    try:
        assert session_base._get_cached_layer_hash(sid, "/tmp/fixture") == "old-file-hash"
        assert session_base._get_cached_layer_hash(sid, "/tmp/fixture") == "old-file-hash"
        assert calls == [("/tmp/fixture", "claude-code")]
        session_base._evict_layer_hash_cache(sid)
        assert session_base._get_cached_layer_hash(sid, "/tmp/fixture") == "new-file-hash"
    finally:
        session_base._evict_layer_hash_cache(sid)


def test_current_python_file_hash_collides_for_distinct_registry_pins(monkeypatch):
    file = {"path": "project:fixture.txt", "hash": "sha256-" + "a" * 64, "content": "fixture"}
    monkeypatch.setattr(layer, "build_layer_manifest", lambda *a, **kw: [file])
    monkeypatch.setattr(layer, "_detect_active_harnesses", lambda: ["claude-code"])
    variants = []
    baseline = json.loads((FIXTURE / "lockfile.json").read_text())["registries"]["https://fixture.invalid"]
    for name, version, listing_id in (
        ("one", "1.0.0", "11111111-1111-4111-8111-111111111111"),
        ("two", "2.0.0", "99999999-9999-4999-8999-999999999999"),
    ):
        registry = json.loads(json.dumps(baseline))
        registry["harnesses"]["claude-code"]["agents"][0]["components"][0].update(
            {"id": listing_id, "version": version, "local_name": name}
        )
        monkeypatch.setattr(lockfile, "read_registry_lockfile", lambda r=registry: ({}, r))
        monkeypatch.setattr(lockfile, "compute_lockfile_hash", lambda: "fixture-hash")
        variants.append((layer.compute_layer_hash("claude-code"), layer.build_upload_payload("claude-code")))
    assert variants[0][0] == variants[1][0] == variants[0][1]["hash"] == variants[1][1]["hash"]
    assert variants[0][1]["pinned_versions"] != variants[1][1]["pinned_versions"]
    assert all("id" not in p["pinned_versions"]["agents"][0]["components"][0] for _, p in variants)
    assert all("local_name" not in p["pinned_versions"]["agents"][0]["components"][0] for _, p in variants)
