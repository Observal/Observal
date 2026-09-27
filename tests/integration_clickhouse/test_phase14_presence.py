# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi
# SPDX-License-Identifier: Apache-2.0

"""Opt-in proof against *isolated* migration-runner database, never the sample.

Run with OBSERVAL_CH_PHASE14_URL=http://127.0.0.1:18123/observal_phase14_ci,
CLICKHOUSE_URL=clickhouse://proof:proof@127.0.0.1:18123/observal_phase14_ci,
and OBSERVAL_CH_PHASE14_USER/PASSWORD=proof. The database must already have
production migrations through 006 applied by the real migration runner.
No existing sample database/tables are altered. Generated project keys isolate
repeat runs; proof rows persist in the dedicated disposable test container.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import pytest

import services.clickhouse.client as clickhouse
from services.layer_components.extractor import ensure_layer_components
from services.layer_components.queries import presence_cohort, presence_coverage

URL = os.getenv("OBSERVAL_CH_PHASE14_URL")
pytestmark = pytest.mark.skipif(not URL, reason="opt-in isolated CH migration proof")
COMPONENT = "11111111-1111-4111-8111-111111111111"
VERSION = "22222222-2222-4222-8222-222222222222"
OTHER_VERSION = "33333333-3333-4333-8333-333333333333"


def _http(sql: str) -> str:
    assert URL is not None
    parsed = urlparse(URL)
    client = urlparse(os.environ.get("CLICKHOUSE_URL", "").replace("clickhouse://", "http://"))
    assert parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    assert parsed.path == "/observal_phase14_ci" and not parsed.query and not parsed.fragment
    assert client.hostname == parsed.hostname and client.port == parsed.port and client.path == parsed.path
    args = urlencode(
        {
            "database": "observal_phase14_ci",
            "user": os.getenv("OBSERVAL_CH_PHASE14_USER", "proof"),
            "password": os.getenv("OBSERVAL_CH_PHASE14_PASSWORD", "proof"),
        }
    )
    endpoint = f"http://{parsed.hostname}:{parsed.port or 18123}/?{args}"
    try:
        with urlopen(Request(endpoint, data=sql.encode(), method="POST"), timeout=30) as response:
            return response.read().decode()
    except Exception as error:
        raise AssertionError(f"isolated ClickHouse query failed ({type(error).__name__})") from None


def _rows(sql: str) -> list[dict]:
    return [json.loads(line) for line in _http(sql + " FORMAT JSONEachRow").splitlines() if line]


def _insert(table: str, rows: list[dict]) -> None:
    assert table in {"session_stats_agg", "layer_snapshots", "layer_components", "layer_component_extractions"} and rows
    _http(f"INSERT INTO {table} FORMAT JSONEachRow\n" + "\n".join(json.dumps(row) for row in rows))


@pytest.fixture(autouse=True)
def _fresh_client_for_pytest_event_loop(monkeypatch):
    monkeypatch.setattr(clickhouse, "_client", None)


@pytest.fixture(scope="module", autouse=True)
def _isolated_runner_proof():
    if not URL:
        pytest.skip("isolated CH proof not configured")
    assert _rows("SELECT currentDatabase() AS db")[0]["db"] == "observal_phase14_ci"
    versions = {item["version"] for item in _rows("SELECT version FROM clickhouse_schema_migrations")}
    assert "006_layer_components" in versions  # Runner, not fixture-only DDL.
    tables = {item["name"] for item in _rows("SELECT name FROM system.tables WHERE database = 'observal_phase14_ci'")}
    assert {"layer_components", "layer_component_extractions", "session_stats_agg"} <= tables


def _marker(
    project: str, user: str, layer_hash: str, generation: int, status: str, version: int = 1, conflict: int = 0
) -> dict:
    return {
        "project_id": project,
        "user_id": user,
        "layer_hash": layer_hash,
        "extractor_version": version,
        "extraction_generation": generation,
        "status": status,
        "identity_conflict": conflict,
    }


def _component(
    project: str,
    user: str,
    layer_hash: str,
    generation: int,
    *,
    component_version: str = VERSION,
    extractor_version: int = 1,
) -> dict:
    return {
        "project_id": project,
        "user_id": user,
        "layer_hash": layer_hash,
        "hash_schema_version": 2,
        "extractor_version": extractor_version,
        "extraction_generation": generation,
        "occurrence_key": "proof-one",
        "component_type": "mcp",
        "source": "standalone",
        "harness": "claude-code",
        "scope": "project",
        "parent_agent_id": "",
        "parent_agent_version": "",
        "raw_listing_id": COMPONENT,
        "raw_name": "probe",
        "raw_version": "1.0.0",
        "qualified_name": "proof/probe",
        "local_name": "probe",
        "component_id": COMPONENT,
        "component_version_id": component_version,
        "identity_status": "resolved",
        "verification_status": "verified",
    }


def _session(project: str, user: str, layer_hash: str, session: str) -> dict:
    return {
        "project_id": project,
        "user_id": user,
        "harness": "claude-code",
        "session_id": session,
        "layer_hash": layer_hash,
        "first_event_time": "2026-01-01 12:00:00.000",
        "last_event_time": "2026-01-01 12:00:00.000",
    }


@pytest.mark.asyncio
async def test_user_project_version_and_latest_complete_publication():
    project = "phase14-" + uuid.uuid4().hex
    other_project = project + "-other"
    layer_hash = "v2_" + "a" * 60
    user, other = "owner", "other"
    period = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))
    _insert(
        "session_stats_agg",
        [
            _session(project, user, layer_hash, "present"),
            _session(project, other, layer_hash, "other-user"),
            _session(other_project, user, layer_hash, "other-project"),
        ],
    )
    _insert(
        "layer_components",
        [
            _component(project, user, layer_hash, 1),
            _component(other_project, user, layer_hash, 1, component_version=OTHER_VERSION),
        ],
    )
    assert await presence_cohort(project, "mcp", COMPONENT, VERSION, period) == []
    _insert(
        "layer_component_extractions",
        [_marker(project, user, layer_hash, 1, "complete"), _marker(other_project, user, layer_hash, 1, "complete")],
    )
    cohort = await presence_cohort(project, "mcp", COMPONENT, VERSION, period)
    assert {(row["user_id"], row["session_id"]) for row in cohort} == {(user, "present")}
    assert await presence_cohort(project, "mcp", COMPONENT, OTHER_VERSION, period) == []
    _insert("layer_component_extractions", [_marker(project, user, layer_hash, 2, "failed")])
    assert len(await presence_cohort(project, "mcp", COMPONENT, VERSION, period)) == 1
    _insert("layer_components", [_component(project, user, layer_hash, 3, component_version=OTHER_VERSION)])
    assert len(await presence_cohort(project, "mcp", COMPONENT, VERSION, period)) == 1
    _insert("layer_component_extractions", [_marker(project, user, layer_hash, 3, "complete")])
    assert await presence_cohort(project, "mcp", COMPONENT, VERSION, period) == []
    assert len(await presence_cohort(project, "mcp", COMPONENT, OTHER_VERSION, period)) == 1
    _insert("layer_component_extractions", [_marker(project, user, layer_hash, 4, "complete", version=2)])
    assert (
        len(await presence_cohort(project, "mcp", COMPONENT, OTHER_VERSION, period)) == 1
    )  # no newer-version fallback
    coverage = await presence_coverage(project, "mcp", COMPONENT, OTHER_VERSION, period)
    assert coverage["eligible_sessions"] == 2 and coverage["present_sessions"] == 1
    assert coverage["present_users"] == 1


@pytest.mark.asyncio
async def test_real_extractor_generation_zero_row_idempotence_and_force():
    parsed = urlparse(os.environ.get("DATABASE_URL", ""))
    if parsed.hostname != "127.0.0.1" or parsed.port != 15432 or parsed.path != "/observal_phase14_ci":
        pytest.skip("requires isolated proof PostgreSQL at localhost:15432")
    project = "phase14-" + uuid.uuid4().hex
    layer_hash = "v2_" + uuid.uuid4().hex + uuid.uuid4().hex[:28]
    _insert(
        "layer_snapshots",
        [
            {
                "project_id": project,
                "user_id": "owner",
                "hash": layer_hash,
                "harness": "claude-code",
                "file_count": 0,
                "total_size": 0,
                "content": json.dumps(
                    {
                        "pinned_versions": {"schema_version": 2, "agents": [], "standalone": []},
                        "drift": {"is_canonical": True},
                    }
                ),
            }
        ],
    )
    first = await ensure_layer_components(project, "owner", layer_hash)
    assert first["status"] == "complete" and first["occurrences"] == 0
    assert (await ensure_layer_components(project, "owner", layer_hash))["status"] == "already_complete"
    rebuilt = await ensure_layer_components(project, "owner", layer_hash, force=True)
    assert rebuilt["generation"] > first["generation"] and rebuilt["occurrences"] == 0
    markers = _rows(
        f"SELECT extraction_generation, status FROM layer_component_extractions "
        f"WHERE project_id = '{project}' ORDER BY extraction_generation"
    )
    assert [row["status"] for row in markers] == ["complete", "complete"]


@pytest.mark.asyncio
async def test_legacy_conflicts_unverified_and_zero_row_publications_are_unknown():
    project = "phase14-" + uuid.uuid4().hex
    user = "owner"
    period = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))
    legacy_hash, layer_hash, zero_hash = "abcdabcdabcdabcd", "v2_" + "b" * 60, "v2_" + "c" * 60
    _insert(
        "session_stats_agg",
        [
            _session(project, user, legacy_hash, "legacy"),
            _session(project, user, layer_hash, "conflict"),
            _session(project, user, zero_hash, "zero"),
        ],
    )
    _insert("layer_components", [_component(project, user, legacy_hash, 1), _component(project, user, layer_hash, 2)])
    _insert(
        "layer_component_extractions",
        [
            _marker(project, user, legacy_hash, 1, "complete"),
            _marker(project, user, layer_hash, 2, "complete", conflict=1),
            _marker(project, user, zero_hash, 3, "complete"),
        ],
    )
    assert await presence_cohort(project, "mcp", COMPONENT, None, period) == []
    coverage = await presence_coverage(project, "mcp", COMPONENT, None, period)
    assert coverage["legacy_hash_sessions"] == 1
    assert coverage["identity_conflict_sessions"] == 1
    assert coverage["mapping_complete_sessions"] == 2  # legacy diagnostics + empty v2 layer
    assert coverage["present_sessions"] == 0
