# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Seed exec dashboard test data into PostgreSQL + ClickHouse.

Run on the EC2 instance (inside the container) or locally with SSH tunnel:
  docker exec observal-api python scripts/seed_exec_dashboard.py
  # or with explicit URLs:
  python scripts/seed_exec_dashboard.py --pg-url postgresql://... --ch-url http://...

Reads DATABASE_URL and CLICKHOUSE_URL from environment by default.
"""

import argparse
import asyncio
import json
import os
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

# Add server source to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server"))

try:
    import asyncpg
    import httpx
except ImportError:
    print("Install dependencies: pip install asyncpg httpx")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEPARTMENTS = ["Engineering", "Data Science", "QA", "Product"]

USERS = [
    ("eng1@acme.corp", "Alex Chen", "Engineering", "power"),
    ("eng2@acme.corp", "Jordan Lee", "Engineering", "moderate"),
    ("eng3@acme.corp", "Sam Rivera", "Engineering", "light"),
    ("eng4@acme.corp", "Pat Morgan", "Engineering", "inactive"),
    ("ds1@acme.corp", "Taylor Kim", "Data Science", "power"),
    ("ds2@acme.corp", "Casey Nguyen", "Data Science", "moderate"),
    ("ds3@acme.corp", "Drew Patel", "Data Science", "inactive"),
    ("qa1@acme.corp", "Riley Zhang", "QA", "power"),
    ("qa2@acme.corp", "Morgan Brooks", "QA", "inactive"),
    ("qa3@acme.corp", "Jamie Foster", "QA", "inactive"),
    ("prod1@acme.corp", "Avery Scott", "Product", "moderate"),
    ("prod2@acme.corp", "Blake Turner", "Product", "inactive"),
]

AGENTS = [
    ("CodeReviewBot", "Code Review", "approved"),
    ("TestGenerator", "Testing", "approved"),
    ("DocWriter", "Documentation", "approved"),
    ("DataPipelineAgent", "Data", "pending"),
    ("SecurityScanner", "Security", "approved"),
    ("PrototypeHelper", "Other", "draft"),
]

AGENT_TEAM_ACCESS = {
    "CodeReviewBot": ["Engineering"],
    "TestGenerator": ["QA"],
    "DocWriter": ["Engineering", "Data Science"],
    "DataPipelineAgent": ["Data Science"],
    "SecurityScanner": ["Engineering"],
    "PrototypeHelper": ["Product"],
}

# user -> (traces/week, agents used, ide, model, cost_range, latency_range)
USER_ACTIVITY = {
    "eng1@acme.corp": (
        40,
        ["CodeReviewBot", "SecurityScanner"],
        "claude-code",
        "claude-sonnet-4-5",
        (0.03, 0.12),
        (800, 3000),
    ),
    "eng2@acme.corp": (15, ["CodeReviewBot", "DocWriter"], "cursor", "claude-sonnet-4-5", (0.03, 0.12), (800, 3000)),
    "eng3@acme.corp": (5, ["DocWriter"], "kiro", "claude-haiku-4-5", (0.005, 0.02), (200, 800)),
    "ds1@acme.corp": (
        30,
        ["DataPipelineAgent", "DocWriter"],
        "claude-code",
        "claude-opus-4-5",
        (0.15, 0.40),
        (2000, 8000),
    ),
    "ds2@acme.corp": (10, ["DocWriter"], "cursor", "claude-sonnet-4-5", (0.03, 0.12), (800, 3000)),
    "qa1@acme.corp": (25, ["TestGenerator"], "claude-code", "claude-sonnet-4-5", (0.03, 0.12), (800, 3000)),
    "prod1@acme.corp": (8, ["PrototypeHelper"], "cursor", "claude-haiku-4-5", (0.005, 0.02), (200, 800)),
}

WEEKS_OF_DATA = 8
PROJECT_ID = "52eb7062-11f8-444e-8f6e-4c906e8d7649"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_pg_url(url: str) -> dict:
    """Parse DATABASE_URL into asyncpg connect kwargs."""
    parsed = urlparse(url.replace("+asyncpg", ""))
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": parsed.username or "postgres",
        "password": parsed.password or "postgres",
        "database": parsed.path.lstrip("/") or "observal",
    }


def parse_ch_url(url: str) -> tuple[str, str, str, str]:
    """Parse CLICKHOUSE_URL into (http_url, db, user, password)."""
    parsed = urlparse(url.replace("clickhouse://", "http://"))
    http_url = f"http://{parsed.hostname}:{parsed.port or 8123}"
    db = parsed.path.strip("/") or "default"
    user = parsed.username or "default"
    password = parsed.password or ""
    return http_url, db, user, password


# ---------------------------------------------------------------------------
# PostgreSQL seeding
# ---------------------------------------------------------------------------


async def seed_postgres(pg_url: str, org_id: str | None, clean: bool) -> dict:
    """Seed PG and return lookup dicts."""
    conn_params = parse_pg_url(pg_url)
    conn = await asyncpg.connect(**conn_params)

    try:
        # Get or create org
        if org_id:
            oid = uuid.UUID(org_id)
        else:
            row = await conn.fetchrow("SELECT id FROM organizations LIMIT 1")
            if row:
                oid = row["id"]
            else:
                oid = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO organizations (id, name, slug) VALUES ($1, $2, $3)",
                    oid,
                    "Acme Corp",
                    "acme",
                )
        print(f"  Org ID: {oid}")

        if clean:
            await conn.execute("DELETE FROM user_groups WHERE user_id IN (SELECT id FROM users WHERE org_id = $1)", oid)
            await conn.execute("DELETE FROM exec_dashboard_config WHERE org_id = $1", oid)
            await conn.execute(
                "DELETE FROM agent_download_records WHERE agent_id IN (SELECT id FROM agents WHERE owner_org_id = $1)",
                oid,
            )
            await conn.execute(
                "DELETE FROM feedback WHERE listing_id IN (SELECT id FROM agents WHERE owner_org_id = $1)", oid
            )
            await conn.execute(
                "DELETE FROM agent_team_access WHERE agent_id IN (SELECT id FROM agents WHERE owner_org_id = $1)", oid
            )
            await conn.execute(
                "DELETE FROM agent_versions WHERE agent_id IN (SELECT id FROM agents WHERE owner_org_id = $1)", oid
            )
            await conn.execute("DELETE FROM agents WHERE owner_org_id = $1", oid)
            await conn.execute("DELETE FROM users WHERE org_id = $1 AND email LIKE '%@acme.corp'", oid)
            print("  Cleaned existing test data")

        # Create users
        user_map: dict[str, uuid.UUID] = {}
        admin_id = None
        for email, name, dept, _ in USERS:
            uid = uuid.uuid4()
            await conn.execute(
                "INSERT INTO users (id, email, name, role, org_id, department, auth_provider, created_at) "
                "VALUES ($1, $2, $3, 'user', $4, $5, 'local', NOW()) ON CONFLICT (email) DO UPDATE SET department = $5 RETURNING id",
                uid,
                email,
                name,
                oid,
                dept,
            )
            row = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
            user_map[email] = row["id"]
            if admin_id is None:
                admin_id = row["id"]

        # Make first user admin (for created_by)
        await conn.execute("UPDATE users SET role = 'admin' WHERE id = $1", admin_id)
        print(f"  Created {len(user_map)} users")

        # Create user_groups (SSO simulation)
        for email, _, dept, _ in USERS:
            uid = user_map[email]
            await conn.execute(
                "INSERT INTO user_groups (id, user_id, group_name, synced_at) VALUES ($1, $2, $3, NOW()) "
                "ON CONFLICT (user_id, group_name) DO NOTHING",
                uuid.uuid4(),
                uid,
                dept,
            )
        print("  Created user_groups entries")

        # Create agents
        agent_map: dict[str, uuid.UUID] = {}
        for agent_name, category, status in AGENTS:
            agent_id = uuid.uuid4()
            version_id = uuid.uuid4()

            await conn.execute(
                "INSERT INTO agents (id, name, owner, category, created_by, owner_org_id, visibility, co_maintainers, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, 'public', '[]'::jsonb, NOW(), NOW()) ON CONFLICT DO NOTHING",
                agent_id,
                agent_name,
                "acme",
                category,
                admin_id,
                oid,
            )
            row = await conn.fetchrow("SELECT id FROM agents WHERE name = $1 AND owner_org_id = $2", agent_name, oid)
            agent_id = row["id"]
            agent_map[agent_name] = agent_id

            await conn.execute(
                "INSERT INTO agent_versions (id, agent_id, version, description, prompt, model_name, model_config_json, models_by_ide, external_mcps, supported_ides, required_ide_features, inferred_supported_ides, status, is_prerelease, download_count, released_by, released_at, created_at, is_editing) "
                "VALUES ($1, $2, '1.0.0', $3, '', '', '{}', '{}', '[]', '[]', '[]', '[]', $4, false, 0, $5, NOW(), NOW(), false) ON CONFLICT DO NOTHING",
                version_id,
                agent_id,
                f"{agent_name} agent",
                status,
                admin_id,
            )
            ver_row = await conn.fetchrow(
                "SELECT id FROM agent_versions WHERE agent_id = $1 ORDER BY created_at DESC LIMIT 1", agent_id
            )
            if ver_row:
                await conn.execute("UPDATE agents SET latest_version_id = $1 WHERE id = $2", ver_row["id"], agent_id)

        print(f"  Created {len(agent_map)} agents")

        # Team access
        for agent_name, groups in AGENT_TEAM_ACCESS.items():
            aid = agent_map.get(agent_name)
            if not aid:
                continue
            for g in groups:
                await conn.execute(
                    "INSERT INTO agent_team_access (id, agent_id, group_name, permission) "
                    "VALUES ($1, $2, $3, 'view') ON CONFLICT DO NOTHING",
                    uuid.uuid4(),
                    aid,
                    g,
                )

        # Downloads
        downloads = {"CodeReviewBot": 45, "TestGenerator": 22, "DocWriter": 35, "SecurityScanner": 15}
        for agent_name, count in downloads.items():
            aid = agent_map.get(agent_name)
            if not aid:
                continue
            for _ in range(count):
                await conn.execute(
                    "INSERT INTO agent_download_records (id, agent_id, user_id, source, installed_at) VALUES ($1, $2, $3, 'cli', $4) ON CONFLICT DO NOTHING",
                    uuid.uuid4(),
                    aid,
                    admin_id,
                    datetime.now(UTC) - timedelta(days=random.randint(0, 60)),
                )
        print("  Inserted download records")

        # Feedback
        feedbacks = [("CodeReviewBot", [5, 4, 4.5]), ("DocWriter", [4, 4, 4, 4, 4]), ("TestGenerator", [4, 3.6])]
        for agent_name, ratings in feedbacks:
            aid = agent_map.get(agent_name)
            if not aid:
                continue
            for rating in ratings:
                await conn.execute(
                    "INSERT INTO feedback (id, listing_id, listing_type, user_id, rating, comment, created_at) VALUES ($1, $2, 'agent', $3, $4, 'Good', NOW())",
                    uuid.uuid4(),
                    aid,
                    admin_id,
                    rating,
                )
        print("  Inserted feedback ratings")

        # Exec dashboard config
        await conn.execute(
            "INSERT INTO exec_dashboard_config (id, org_id, hourly_dev_cost, pre_ai_baselines, department_budgets, target_adoption_pct, created_at, updated_at) "
            "VALUES ($1, $2, 85.00, $3, $4, 80, NOW(), NOW()) ON CONFLICT (org_id) DO UPDATE SET hourly_dev_cost = 85.00, pre_ai_baselines = $3",
            uuid.uuid4(),
            oid,
            json.dumps(
                {
                    "Code Review": 0.50,
                    "Testing": 0.35,
                    "Documentation": 0.25,
                    "Data": 0.45,
                    "Security": 0.40,
                    "Other": 0.30,
                }
            ),
            json.dumps({"Engineering": 5000, "Data Science": 3000, "QA": 2000, "Product": 1000}),
        )
        print("  Created exec_dashboard_config")

        return {"org_id": oid, "user_map": user_map, "agent_map": agent_map}

    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# ClickHouse seeding
# ---------------------------------------------------------------------------


async def seed_clickhouse(ch_url: str, user_map: dict, agent_map: dict, clean: bool):
    """Seed traces, spans, and session_events."""
    http_url, db, ch_user, ch_pass = parse_ch_url(ch_url)
    params = {"database": db, "user": ch_user, "password": ch_pass}

    async with httpx.AsyncClient(timeout=30) as client:

        async def ch_query(sql: str, data: str | None = None):
            body = f"{sql}\n{data}" if data else sql
            r = await client.post(http_url, params=params, content=body)
            if r.status_code != 200:
                print(f"    CH error: {r.text[:200]}")
            return r

        if clean:
            await ch_query("TRUNCATE TABLE IF EXISTS traces")
            await ch_query("TRUNCATE TABLE IF EXISTS spans")
            await ch_query("TRUNCATE TABLE IF EXISTS session_events")
            print("  Cleaned ClickHouse tables")

        now = datetime.now(UTC)
        trace_rows = []
        span_rows = []
        session_event_rows = []

        for email, activity in USER_ACTIVITY.items():
            traces_per_week, agent_names, ide, model, cost_range, latency_range = activity
            uid = str(user_map.get(email, ""))
            if not uid:
                continue

            for week_offset in range(WEEKS_OF_DATA):
                week_start = now - timedelta(weeks=WEEKS_OF_DATA - week_offset)
                count = traces_per_week + random.randint(-3, 3)

                for _ in range(max(1, count)):
                    trace_id = str(uuid.uuid4())
                    agent_name = random.choice(agent_names)
                    agent_id = str(agent_map.get(agent_name, ""))
                    start_time = week_start + timedelta(
                        days=random.randint(0, 6),
                        hours=random.randint(8, 18),
                        minutes=random.randint(0, 59),
                    )

                    trace_rows.append(
                        json.dumps(
                            {
                                "trace_id": trace_id,
                                "project_id": PROJECT_ID,
                                "agent_id": agent_id,
                                "user_id": uid,
                                "ide": ide,
                                "start_time": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "trace_type": "agent",
                                "name": agent_name,
                                "is_deleted": 0,
                                "event_ts": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                            }
                        )
                    )

                    # 2-6 spans per trace
                    num_spans = random.randint(2, 6)
                    session_tokens = 0
                    session_cost = 0.0

                    for s_idx in range(num_spans):
                        span_id = str(uuid.uuid4())
                        cost = round(random.uniform(*cost_range), 4)
                        latency = random.randint(*latency_range)
                        input_tokens = random.randint(200, 4000)
                        output_tokens = random.randint(100, 3000)
                        # 5% error rate, but SecurityScanner gets 25%
                        error_chance = 0.25 if agent_name == "SecurityScanner" else 0.05
                        status = "error" if random.random() < error_chance else "success"

                        session_tokens += input_tokens + output_tokens
                        session_cost += cost

                        span_rows.append(
                            json.dumps(
                                {
                                    "span_id": span_id,
                                    "trace_id": trace_id,
                                    "project_id": PROJECT_ID,
                                    "agent_id": agent_id,
                                    "user_id": uid,
                                    "type": "llm",
                                    "name": model,
                                    "start_time": (start_time + timedelta(seconds=s_idx)).strftime("%Y-%m-%dT%H:%M:%S"),
                                    "latency_ms": latency,
                                    "status": status,
                                    "cost": cost,
                                    "token_count_input": input_tokens,
                                    "token_count_output": output_tokens,
                                    "token_count_total": input_tokens + output_tokens,
                                    "ide": ide,
                                    "is_deleted": 0,
                                    "event_ts": (start_time + timedelta(seconds=s_idx)).strftime("%Y-%m-%dT%H:%M:%S"),
                                }
                            )
                        )

                    # Session events for session_stats_agg
                    session_id = str(uuid.uuid4())
                    session_event_rows.append(
                        json.dumps(
                            {
                                "session_id": session_id,
                                "project_id": PROJECT_ID,
                                "user_id": uid,
                                "ide": ide,
                                "model": model,
                                "agent_id": agent_id,
                                "event_type": "session_end",
                                "timestamp": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "input_tokens": session_tokens // 2,
                                "output_tokens": session_tokens // 2,
                                "credits": session_cost,
                            }
                        )
                    )

        # Insert in batches
        batch_size = 500
        print(f"  Inserting {len(trace_rows)} traces...")
        for i in range(0, len(trace_rows), batch_size):
            batch = "\n".join(trace_rows[i : i + batch_size])
            await ch_query("INSERT INTO traces FORMAT JSONEachRow", batch)

        print(f"  Inserting {len(span_rows)} spans...")
        for i in range(0, len(span_rows), batch_size):
            batch = "\n".join(span_rows[i : i + batch_size])
            await ch_query("INSERT INTO spans FORMAT JSONEachRow", batch)

        print(f"  Inserting {len(session_event_rows)} session events...")
        for i in range(0, len(session_event_rows), batch_size):
            batch = "\n".join(session_event_rows[i : i + batch_size])
            await ch_query("INSERT INTO session_events FORMAT JSONEachRow", batch)

        print(f"  Done: {len(trace_rows)} traces, {len(span_rows)} spans, {len(session_event_rows)} sessions")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    parser = argparse.ArgumentParser(description="Seed exec dashboard test data")
    parser.add_argument(
        "--pg-url",
        default=os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/observal"),
    )
    parser.add_argument("--ch-url", default=os.environ.get("CLICKHOUSE_URL", "clickhouse://localhost:8123/observal"))
    parser.add_argument("--org-id", default=None, help="Existing org UUID to use")
    parser.add_argument("--clean", action="store_true", help="Delete existing test data first")
    args = parser.parse_args()

    print("=== Exec Dashboard Seed Script ===\n")

    print("[1/2] Seeding PostgreSQL...")
    result = await seed_postgres(args.pg_url, args.org_id, args.clean)

    print("\n[2/2] Seeding ClickHouse...")
    await seed_clickhouse(args.ch_url, result["user_map"], result["agent_map"], args.clean)

    print("\n=== Done ===")
    print(f"Org ID: {result['org_id']}")
    print(f"Users: {len(result['user_map'])}")
    print(f"Agents: {len(result['agent_map'])}")
    print("\nTo verify: python scripts/verify_exec_dashboard.py --base-url <URL> --token <ADMIN_JWT>")


if __name__ == "__main__":
    asyncio.run(main())
