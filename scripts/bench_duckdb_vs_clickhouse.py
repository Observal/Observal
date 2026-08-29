# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Benchmark: DuckDB port vs ClickHouse, on Observal's real workload shapes.

Generates synthetic-but-realistic AI session telemetry (repetitive JSONL
envelopes: shared system-prompt boilerplate, repeated tool schemas), loads it
into both engines via each engine's real code path, then times the actual
query patterns used by the API routes.

Usage (from observal-server/):
    DUCKDB_PATH=/tmp/bench.duckdb python ../scripts/bench_duckdb_vs_clickhouse.py \
        --clickhouse-url http://localhost:18123 --sessions 200 --events 500

Requires a running ClickHouse (docker run -p 18123:8123 ...). DuckDB runs
in-process via the ported services.duckdb package.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server"))

CH_URL = ""
CH_DB = "observal_bench"

# ── ClickHouse side (raw HTTP, mirroring the legacy client) ──────────────────


def ch_exec(sql: str, data: str | None = None, params: dict | None = None) -> tuple[int, str]:
    from urllib.parse import urlencode

    q = {"user": "default", "password": os.environ.get("CH_PASSWORD", "clickhouse"), "database": CH_DB}
    if params:
        q.update(params)
    body = f"{sql}\n{data}" if data else sql
    req = urllib.request.Request(
        f"{CH_URL}/?{urlencode(q)}", data=body.encode(), headers={"Content-Type": "text/plain"}
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
        except urllib.error.URLError:
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))


def ch_setup() -> None:
    """Create the bench DB and apply the repo's real ClickHouse migrations."""
    global CH_DB
    status, text = ch_exec("CREATE DATABASE IF NOT EXISTS observal_bench", params={"database": "default"})
    assert status == 200, text

    mig_dir = Path(__file__).resolve().parent.parent / "observal-server" / "clickhouse" / "migrations"
    # Import the splitter from the ported package (same logic, engine-agnostic).
    from services.duckdb.migrations import _split_sql

    for path in sorted(mig_dir.glob("*.sql")):
        for stmt in _split_sql(path.read_text()):
            status, text = ch_exec(stmt)
            if status != 200:
                raise RuntimeError(f"CH migration {path.name} failed: {text[:300]}")


def ch_insert_events(rows: list[dict]) -> None:
    cols = (
        "session_id, project_id, user_id, agent_id, agent_version, layer_hash, harness, "
        "line_offset, source_end_offset, line_hash, source_sha256, is_source_record, rendered, "
        "event_type, timestamp, uuid, parent_uuid, tool_name, tool_id, content_preview, "
        "content_length, raw_line, credits, parent_session_id, input_tokens, output_tokens, "
        "cache_read_tokens, cache_write_tokens, model, raw_line_truncated"
    )
    data = "\n".join(json.dumps({k: r.get(k) for k in cols.split(", ")}, default=str) for r in rows)
    status, text = ch_exec(
        f"INSERT INTO session_events ({cols}) FORMAT JSONEachRow",
        data=data,
        params={"wait_for_async_insert": "1"},
    )
    if status != 200:
        raise RuntimeError(f"CH insert failed: {text[:300]}")


def ch_query_json(sql: str) -> list[dict]:
    status, text = ch_exec(f"{sql} FORMAT JSON")
    if status != 200:
        raise RuntimeError(f"CH query failed: {text[:300]}")
    return json.loads(text).get("data", [])


# ── Synthetic data ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an AI coding assistant with access to tools. Follow these rules carefully. "
    "Always read files before editing. Prefer exact replacements. Run tests after changes. "
) * 12
TOOL_SCHEMA = json.dumps(
    {
        "name": "read",
        "description": "Read a file from disk with optional offset and limit parameters",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}},
            "required": ["path"],
        },
    }
)
WORDS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "mu"]


def gen_sessions(n_sessions: int, events_per: int, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    harnesses = ["claude_code", "cursor", "pi", "kiro"]
    models = ["claude-4", "gpt-5", "gemini-3"]
    base_ts = int(time.time()) - 7 * 86400
    for s in range(n_sessions):
        sid = f"session-{s:05d}"
        uid = f"user-{s % 25:03d}"
        harness = harnesses[s % len(harnesses)]
        model = models[s % len(models)]
        credits = 0.0
        for i in range(events_per):
            etype = ["user_prompt", "tool_call", "tool_result"][i % 3]
            ts = base_ts + s * 60 + i
            credits += rng.uniform(0.001, 0.02)
            if etype == "user_prompt":
                raw = json.dumps(
                    {"type": "user", "system": SYSTEM_PROMPT, "text": " ".join(rng.choices(WORDS, k=30))}
                )
            elif etype == "tool_call":
                raw = json.dumps(
                    {"type": "tool_use", "name": "read", "schema": TOOL_SCHEMA, "input": {"path": f"/src/f{i}.py"}}
                )
            else:
                raw = json.dumps({"type": "tool_result", "content": " ".join(rng.choices(WORDS, k=40))})
            rows.append(
                {
                    "session_id": sid,
                    "project_id": "default",
                    "user_id": uid,
                    "agent_id": f"agent-{s % 40:03d}",
                    "agent_version": f"{1 + s % 5}.0.0",
                    "layer_hash": f"layer-{s % 60:03d}",
                    "harness": harness,
                    "line_offset": i,
                    "source_end_offset": (i + 1) * len(raw),
                    "line_hash": f"hash-{s}-{i}",
                    "source_sha256": f"sha-{s}-{i}",
                    "is_source_record": 1,
                    "rendered": 1,
                    "event_type": etype,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S.000", time.gmtime(ts)),
                    "uuid": None,
                    "parent_uuid": None,
                    "tool_name": "read" if etype == "tool_call" else None,
                    "tool_id": f"toolu_{s}_{i}" if etype == "tool_call" else None,
                    "content_preview": raw[:100],
                    "content_length": len(raw),
                    "raw_line": raw,
                    "credits": round(credits, 6),
                    "parent_session_id": None,
                    "input_tokens": rng.randint(50, 4000),
                    "output_tokens": rng.randint(10, 1500),
                    "cache_read_tokens": rng.randint(0, 8000),
                    "cache_write_tokens": rng.randint(0, 2000),
                    "model": model,
                    "raw_line_truncated": 0,
                }
            )
    return rows


# ── Timing harness ───────────────────────────────────────────────────────────


def bench(fn, iterations: int) -> dict:
    samples = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return {
        "p50": statistics.median(samples),
        "p95": samples[max(0, int(len(samples) * 0.95) - 1)],
        "min": samples[0],
    }


QUERIES = {
    "replay (one session, ordered)": {
        "ch": "SELECT line_offset, event_type, tool_name, content_length FROM session_events FINAL "
        "WHERE project_id = 'default' AND user_id = '{uid}' AND harness = '{harness}' "
        "AND session_id = '{sid}' ORDER BY line_offset",
        "ddb": "SELECT line_offset, event_type, tool_name, content_length FROM session_events "
        "WHERE project_id = 'default' AND user_id = $uid AND harness = $harness "
        "AND session_id = $sid ORDER BY line_offset",
    },
    "dedup range scan": {
        "ch": "SELECT line_offset, line_hash FROM session_events FINAL "
        "WHERE project_id = 'default' AND user_id = '{uid}' AND harness = '{harness}' "
        "AND session_id = '{sid}' AND is_source_record = 1 AND line_offset >= 100 AND line_offset <= 400",
        "ddb": "SELECT line_offset, line_hash FROM session_events "
        "WHERE project_id = 'default' AND user_id = $uid AND harness = $harness "
        "AND session_id = $sid AND is_source_record = 1 AND line_offset >= 100 AND line_offset <= 400",
    },
    "dashboard: sessions by harness": {
        "ch": "SELECT harness, count() AS c, sum(tool_call_count) AS tools FROM session_stats_agg FINAL "
        "GROUP BY harness",
        "ddb": "SELECT harness, count(*) AS c, sum(tool_call_count) AS tools FROM session_stats_agg "
        "GROUP BY harness",
    },
    "dashboard: model token leaderboard": {
        "ch": "SELECT model, sum(input_tokens + output_tokens) AS tokens, "
        "countIf(event_count > 5 AND prompt_count >= 1) AS completed "
        "FROM session_stats_agg FINAL GROUP BY model ORDER BY tokens DESC",
        "ddb": "SELECT model, sum(input_tokens + output_tokens) AS tokens, "
        "count(*) FILTER (WHERE event_count > 5 AND prompt_count >= 1) AS completed "
        "FROM session_stats_agg GROUP BY model ORDER BY tokens DESC",
    },
    "recent activity (60m)": {
        "ch": "SELECT sum(tool_call_count) AS tools, count() AS sessions FROM session_stats_agg FINAL "
        "WHERE last_event_time > now() - INTERVAL 60 MINUTE",
        "ddb": "SELECT sum(tool_call_count) AS tools, count(*) AS sessions FROM session_stats_agg "
        "WHERE last_event_time > now()::TIMESTAMP - INTERVAL '60 minutes'",
    },
    "audit time-range scan (7d)": {
        "ch": "SELECT event_id, timestamp, action FROM audit_log "
        "WHERE timestamp >= now() - INTERVAL 7 DAY ORDER BY timestamp DESC LIMIT 100",
        "ddb": "SELECT event_id, timestamp, action FROM audit_log "
        "WHERE timestamp >= now()::TIMESTAMP - INTERVAL '7 days' ORDER BY timestamp DESC LIMIT 100",
    },
}


def main() -> None:
    global CH_URL
    parser = argparse.ArgumentParser()
    parser.add_argument("--clickhouse-url", default="http://localhost:18123")
    parser.add_argument("--sessions", type=int, default=200)
    parser.add_argument("--events", type=int, default=500)
    parser.add_argument("--audit-rows", type=int, default=50_000)
    parser.add_argument("--iterations", type=int, default=30)
    args = parser.parse_args()
    CH_URL = args.clickhouse_url

    n = args.sessions * args.events
    print(f"workload: {args.sessions} sessions x {args.events} events = {n:,} rows + {args.audit_rows:,} audit rows")

    rows = gen_sessions(args.sessions, args.events)
    audit_rows = [
        {
            "event_id": str(uuid.UUID(int=i + 1)),
            "timestamp": rows[i % len(rows)]["timestamp"],
            "actor_id": f"user-{i % 25:03d}",
            "actor_email": f"user{i % 25}@example.com",
            "actor_role": "admin",
            "action": ["agent.publish", "user.login", "settings.update"][i % 3],
            "resource_type": "agent",
            "resource_id": f"agent-{i % 40:03d}",
            "resource_name": "",
            "http_method": "POST",
            "http_path": "/api/v1/agents",
            "status_code": 200,
            "ip_address": "10.0.0.1",
            "user_agent": "cli",
            "detail": "{}",
            "sensitivity": "standard",
            "request_id": f"req-{i}",
            "outcome": "success",
            "duration_ms": 12.5,
            "chain_hash": "a" * 64,
            "source": "server",
        }
        for i in range(args.audit_rows)
    ]

    # ── Ingest: ClickHouse ──
    ch_setup()
    t0 = time.perf_counter()
    batch = 2000
    for i in range(0, len(rows), batch):
        ch_insert_events(rows[i : i + batch])
    ch_ingest = time.perf_counter() - t0
    for i in range(0, len(audit_rows), batch):
        status, text = ch_exec(
            "INSERT INTO audit_log (event_id, timestamp, actor_id, actor_email, actor_role, action, "
            "resource_type, resource_id, resource_name, http_method, http_path, status_code, ip_address, "
            "user_agent, detail, sensitivity, request_id, outcome, duration_ms, chain_hash, source) "
            "SETTINGS async_insert=0 FORMAT JSONEachRow",
            data="\n".join(json.dumps(r) for r in audit_rows[i : i + batch]),
        )
        if status != 200:
            raise RuntimeError(f"CH audit insert failed: {text[:300]}")
    ch_exec("OPTIMIZE TABLE session_events FINAL")
    ch_exec("OPTIMIZE TABLE audit_log FINAL")
    # CH populates session_stats_agg via its materialized view.
    time.sleep(1)

    # ── Ingest: DuckDB (real ported code path) ──
    os.environ.setdefault("DUCKDB_PATH", "/tmp/bench_observal.duckdb")
    if os.path.exists(os.environ["DUCKDB_PATH"]):
        os.remove(os.environ["DUCKDB_PATH"])

    async def duckdb_ingest():
        from services.duckdb.insert import insert_audit_log, insert_session_events
        from services.duckdb.migrations import run_duckdb_migrations

        await run_duckdb_migrations()
        t0 = time.perf_counter()
        for i in range(0, len(rows), batch):
            await insert_session_events(rows[i : i + batch])
        ddb_ingest = time.perf_counter() - t0
        for i in range(0, len(audit_rows), batch):
            await insert_audit_log(audit_rows[i : i + batch])
        return ddb_ingest

    ddb_ingest = asyncio.run(duckdb_ingest())

    # DuckDB maintains the rollup in app code (refresh per session).
    async def duckdb_refresh():
        from services.duckdb import refresh_session_summary

        t0 = time.perf_counter()
        for s in range(args.sessions):
            await refresh_session_summary(
                f"session-{s:05d}", "default", f"user-{s % 25:03d}", ["claude_code", "cursor", "pi", "kiro"][s % 4]
            )
        return time.perf_counter() - t0

    ddb_rollup = asyncio.run(duckdb_refresh())

    from services.duckdb import _query

    print(f"\n── ingest ({n:,} events) ──")
    print(f"  ClickHouse HTTP JSONEachRow : {ch_ingest:6.2f}s  ({n / ch_ingest:9,.0f} rows/s)")
    print(f"  DuckDB Arrow batch          : {ddb_ingest:6.2f}s  ({n / ddb_ingest:9,.0f} rows/s)")
    print(f"  DuckDB rollup refresh ({args.sessions} sessions): {ddb_rollup:.2f}s")

    # ── Query benchmarks ──
    print(f"\n── query latency ({args.iterations} iterations each) ──")
    print(f"  {'query':<40} {'CH p50':>9} {'DDB p50':>9} {'CH p95':>9} {'DDB p95':>9}")
    results = {}
    for name, q in QUERIES.items():
        ch_sql_tpl, ddb_sql = q["ch"], q["ddb"]

        def pick():
            s = random.randrange(args.sessions)
            return f"session-{s:05d}", f"user-{s % 25:03d}", ["claude_code", "cursor", "pi", "kiro"][s % 4]

        def ch_run(ch_sql_tpl=ch_sql_tpl):
            sid, uid, harness = pick()
            ch_query_json(ch_sql_tpl.format(sid=sid, uid=uid, harness=harness))

        def ddb_run(ddb_sql=ddb_sql):
            sid, uid, harness = pick()

            async def go():
                r = await _query(ddb_sql, {"sid": sid, "uid": uid, "harness": harness})
                r.raise_for_status()
                r.json()

            asyncio.run(go())

        ch_r = bench(ch_run, args.iterations)
        ddb_r = bench(ddb_run, args.iterations)
        results[name] = (ch_r, ddb_r)
        print(
            f"  {name:<40} {ch_r['p50']:8.1f}m {ddb_r['p50']:8.1f}m {ch_r['p95']:8.1f}m {ddb_r['p95']:8.1f}m"
        )

    # ── Storage footprint ──
    _, parts = ch_exec(
        "SELECT table, formatReadableSize(sum(bytes_on_disk)) FROM system.parts "
        f"WHERE database = '{CH_DB}' AND active GROUP BY table FORMAT JSON"
    )
    ch_sizes = {r["table"]: r["formatReadableSize(sum(bytes_on_disk))"] for r in json.loads(parts)["data"]}
    asyncio.run(_query("CHECKPOINT"))
    ddb_size = os.path.getsize(os.environ["DUCKDB_PATH"])

    def mb(s: str) -> float:
        num, _, unit = s.partition(" ")
        mult = {"B": 1e-6, "KiB": 1e-3, "MiB": 1, "GiB": 1e3}[unit]
        return float(num) * mult

    ch_total_mb = sum(mb(v) for v in ch_sizes.values())
    print("\n── storage footprint ──")
    print(f"  ClickHouse on-disk total : {ch_total_mb:8.1f} MB  {ch_sizes}")
    print(f"  DuckDB file              : {ddb_size / 1e6:8.1f} MB")


if __name__ == "__main__":
    main()
