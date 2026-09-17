# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Seed exec dashboard test data into PostgreSQL + the DuckDB analytics store.

Run on the data host (inside the API container) or locally:
  docker exec observal-api python scripts/seed_exec_dashboard.py
  # or with explicit URLs:
  python scripts/seed_exec_dashboard.py \
      --pg-url postgresql://... \
      --duckdb-url duckdb://localhost:8484/observal

Reads DATABASE_URL, DUCKDB_ANALYTICS_URL, and DUCKDB_ANALYTICS_TOKEN from the
environment by default. Sessions land in ``session_events`` and their summaries
are recomputed with the same helper the ingest path uses, which is what the
exec dashboard reads.
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

from observal_shared.migration.constants import DEFAULT_PROJECT_ID

try:
    import asyncpg
except ImportError:
    print("Install dependencies: pip install asyncpg")
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


# user -> (sessions/week, agents used, harness, model, cost_range)
USER_ACTIVITY = {
    "eng1@acme.corp": (
        40,
        ["CodeReviewBot", "SecurityScanner"],
        "claude-code",
        "claude-sonnet-4-5",
        (0.03, 0.12),
    ),
    "eng2@acme.corp": (15, ["CodeReviewBot", "DocWriter"], "cursor", "claude-sonnet-4-5", (0.03, 0.12)),
    "eng3@acme.corp": (5, ["DocWriter"], "kiro", "claude-haiku-4-5", (0.005, 0.02)),
    "ds1@acme.corp": (
        30,
        ["DataPipelineAgent", "DocWriter"],
        "claude-code",
        "claude-opus-4-5",
        (0.15, 0.40),
    ),
    "ds2@acme.corp": (10, ["DocWriter"], "cursor", "claude-sonnet-4-5", (0.03, 0.12)),
    "qa1@acme.corp": (25, ["TestGenerator"], "claude-code", "claude-sonnet-4-5", (0.03, 0.12)),
    "prod1@acme.corp": (8, ["PrototypeHelper"], "cursor", "claude-haiku-4-5", (0.005, 0.02)),
}

WEEKS_OF_DATA = 8

PROJECT_ID = DEFAULT_PROJECT_ID


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


# ---------------------------------------------------------------------------
# PostgreSQL seeding
# ---------------------------------------------------------------------------


async def seed_postgres(pg_url: str, clean: bool) -> dict:
    """Seed deployment-wide dashboard data and return lookup dicts."""
    conn = await asyncpg.connect(**parse_pg_url(pg_url))
    try:
        old_user_ids: list[uuid.UUID] = []
        if clean:
            old_user_rows = await conn.fetch("SELECT id FROM users WHERE email LIKE '%@acme.corp'")
            old_user_ids = [row["id"] for row in old_user_rows]
            agent_names = [name for name, _, _ in AGENTS]
            agent_rows = await conn.fetch("SELECT id FROM agents WHERE name = ANY($1::text[])", agent_names)
            for row in agent_rows:
                await conn.execute("DELETE FROM agent_download_records WHERE agent_id = $1", row["id"])
                await conn.execute("DELETE FROM feedback WHERE listing_id = $1", row["id"])
                await conn.execute("DELETE FROM agent_versions WHERE agent_id = $1", row["id"])
                await conn.execute("DELETE FROM agents WHERE id = $1", row["id"])
            await conn.execute("DELETE FROM exec_dashboard_config")
            await conn.execute(
                "DELETE FROM user_groups WHERE user_id IN (SELECT id FROM users WHERE email LIKE '%@acme.corp')"
            )
            await conn.execute("DELETE FROM users WHERE email LIKE '%@acme.corp'")
            print("  Cleaned existing test data")

        user_map: dict[str, uuid.UUID] = {}
        admin_id = None
        for email, name, dept, _ in USERS:
            row = await conn.fetchrow(
                "INSERT INTO users (id, email, username, name, role, department, auth_provider, created_at) "
                "VALUES ($1, $2, $3, $4, 'user', $5, 'local', NOW()) "
                "ON CONFLICT (email) DO UPDATE SET department = $5 RETURNING id",
                uuid.uuid4(),
                email,
                email.split("@", 1)[0][:32],
                name,
                dept,
            )
            user_map[email] = row["id"]
            if admin_id is None:
                admin_id = row["id"]

        await conn.execute("UPDATE users SET role = 'admin' WHERE id = $1", admin_id)
        print(f"  Created {len(user_map)} users")

        for email, _, dept, _ in USERS:
            await conn.execute(
                "INSERT INTO user_groups (id, user_id, group_name, synced_at) VALUES ($1, $2, $3, NOW()) "
                "ON CONFLICT (user_id, group_name) DO NOTHING",
                uuid.uuid4(),
                user_map[email],
                dept,
            )
        print("  Created user_groups entries")

        agent_map: dict[str, uuid.UUID] = {}
        for agent_name, category, status in AGENTS:
            row = await conn.fetchrow(
                "INSERT INTO agents (id, name, namespace, slug, owner, is_private, category, created_by, co_authors, created_at, updated_at) "
                "VALUES ($1, $2, 'seed', $3, 'seed', false, $4, $5, '[]'::jsonb, NOW(), NOW()) "
                "ON CONFLICT (namespace, slug) WHERE deleted_at IS NULL "
                "DO UPDATE SET category = EXCLUDED.category RETURNING id",
                uuid.uuid4(),
                agent_name,
                agent_name.lower(),
                category,
                admin_id,
            )
            agent_id = row["id"]
            agent_map[agent_name] = agent_id
            version_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO agent_versions (id, agent_id, version, description, prompt, model_name, model_config_json, "
                "models_by_harness, external_mcps, supported_harnesses, required_capabilities, "
                "inferred_supported_harnesses, status, is_prerelease, download_count, released_by, released_at, "
                "created_at, is_editing) VALUES ($1, $2, '1.0.0', $3, '', '', '{}', '{}', '[]', '[]', '[]', '[]', "
                "$4, false, 0, $5, NOW(), NOW(), false) ON CONFLICT DO NOTHING",
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

        downloads = {"CodeReviewBot": 45, "TestGenerator": 22, "DocWriter": 35, "SecurityScanner": 15}
        for agent_name, count in downloads.items():
            agent_id = agent_map.get(agent_name)
            if not agent_id:
                continue
            for _ in range(count):
                await conn.execute(
                    "INSERT INTO agent_download_records (id, agent_id, user_id, source, installed_at) "
                    "VALUES ($1, $2, $3, 'cli', $4) ON CONFLICT DO NOTHING",
                    uuid.uuid4(),
                    agent_id,
                    admin_id,
                    datetime.now(UTC) - timedelta(days=random.randint(0, 60)),
                )
        print("  Inserted download records")

        feedbacks = [("CodeReviewBot", [5, 4, 4.5]), ("DocWriter", [4, 4, 4, 4, 4]), ("TestGenerator", [4, 3.6])]
        # One rating per user per listing: the schema enforces that pair as unique.
        reviewers = [uid for email, uid in user_map.items() if email != USERS[0][0]]
        for agent_name, ratings in feedbacks:
            agent_id = agent_map.get(agent_name)
            if not agent_id:
                continue
            for idx, rating in enumerate(ratings):
                await conn.execute(
                    "INSERT INTO feedback (id, listing_id, listing_type, user_id, rating, comment, created_at) "
                    "VALUES ($1, $2, 'agent', $3, $4, 'Good', NOW()) "
                    "ON CONFLICT (user_id, listing_id, listing_type) DO UPDATE SET rating = EXCLUDED.rating",
                    uuid.uuid4(),
                    agent_id,
                    reviewers[idx % len(reviewers)],
                    rating,
                )
        print("  Inserted feedback ratings")

        baselines = json.dumps(
            {
                "Code Review": 0.50,
                "Testing": 0.35,
                "Documentation": 0.25,
                "Data": 0.45,
                "Security": 0.40,
                "Other": 0.30,
            }
        )
        budgets = json.dumps({"Engineering": 5000, "Data Science": 3000, "QA": 2000, "Product": 1000})
        # The table holds exactly one row (unique index on a constant expression),
        # so update it in place when it already exists.
        config_id = await conn.fetchval("SELECT id FROM exec_dashboard_config LIMIT 1")
        if config_id:
            await conn.execute(
                "UPDATE exec_dashboard_config SET hourly_dev_cost = 85.00, pre_ai_baselines = $1, "
                "department_budgets = $2, target_adoption_pct = 80, updated_at = NOW() WHERE id = $3",
                baselines,
                budgets,
                config_id,
            )
            print("  Updated exec_dashboard_config")
        else:
            await conn.execute(
                "INSERT INTO exec_dashboard_config (id, hourly_dev_cost, pre_ai_baselines, department_budgets, "
                "target_adoption_pct, created_at, updated_at) VALUES ($1, 85.00, $2, $3, 80, NOW(), NOW())",
                uuid.uuid4(),
                baselines,
                budgets,
            )
            print("  Created exec_dashboard_config")
        return {"user_map": user_map, "agent_map": agent_map, "old_user_ids": old_user_ids}
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# DuckDB analytics seeding
# ---------------------------------------------------------------------------


async def seed_analytics(
    duckdb_url: str,
    duckdb_token: str,
    user_map: dict,
    agent_map: dict,
    clean: bool,
    old_user_ids: list[uuid.UUID] | None = None,
):
    """Seed session events plus their summaries into the DuckDB analytics store."""
    os.environ["DUCKDB_ANALYTICS_URL"] = duckdb_url
    if duckdb_token:
        os.environ["DUCKDB_ANALYTICS_TOKEN"] = duckdb_token

    from services.analytics.duckdb import client as analytics_client
    from services.analytics.duckdb.insert import insert_session_events, refresh_session_summary

    if clean and old_user_ids:
        # Capture these IDs before PostgreSQL replaces the demo users. The
        # deployment-wide project ID is shared with real telemetry and must
        # never be used as the cleanup boundary.
        ids = [str(user_id) for user_id in old_user_ids]
        params = {"ids": ids}
        predicate = "list_contains(CAST($ids AS VARCHAR[]), user_id)"
        await analytics_client._execute(f"DELETE FROM session_stats_agg WHERE {predicate}", params)
        await analytics_client._execute(f"DELETE FROM session_events WHERE {predicate}", params)
        print("  Cleaned seeded analytics rows")

    now = datetime.now(UTC)
    session_event_rows: list[dict] = []
    session_keys: list[tuple[str, str, str]] = []

    for email, activity in USER_ACTIVITY.items():
        sessions_per_week, agent_names, harness, model, cost_range = activity
        uid = str(user_map.get(email, ""))
        if not uid:
            continue

        for week_offset in range(WEEKS_OF_DATA):
            week_start = now - timedelta(weeks=WEEKS_OF_DATA - week_offset)
            count = sessions_per_week + random.randint(-3, 3)

            for _ in range(max(1, count)):
                session_id = str(uuid.uuid4())
                agent_name = random.choice(agent_names)
                agent_id = str(agent_map.get(agent_name, ""))
                start_time = week_start + timedelta(
                    days=random.randint(0, 6),
                    hours=random.randint(8, 18),
                    minutes=random.randint(0, 59),
                )
                session_keys.append((session_id, uid, harness))

                # One prompt plus 2-6 tool round trips, then the session total.
                num_spans = random.randint(2, 6)
                session_tokens = 0
                session_cost = 0.0
                line_offset = 0

                session_event_rows.append(
                    {
                        "session_id": session_id,
                        "project_id": PROJECT_ID,
                        "user_id": uid,
                        "agent_id": agent_id,
                        "harness": harness,
                        "line_offset": line_offset,
                        "event_type": "user_prompt",
                        "timestamp": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "model": model,
                        "content_preview": f"{agent_name} session",
                        "content_length": len(agent_name) + 8,
                    }
                )

                for s_idx in range(num_spans):
                    line_offset += 1
                    cost = round(random.uniform(*cost_range), 4)
                    input_tokens = random.randint(200, 4000)
                    output_tokens = random.randint(100, 3000)
                    session_tokens += input_tokens + output_tokens
                    session_cost += cost
                    event_time = (start_time + timedelta(seconds=30 * s_idx)).strftime("%Y-%m-%d %H:%M:%S")

                    session_event_rows.append(
                        {
                            "session_id": session_id,
                            "project_id": PROJECT_ID,
                            "user_id": uid,
                            "agent_id": agent_id,
                            "harness": harness,
                            "line_offset": line_offset,
                            "event_type": "tool_call",
                            "timestamp": event_time,
                            "model": model,
                            "tool_name": model,
                            "tool_id": str(uuid.uuid4()),
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "content_preview": f"{model} call",
                            "content_length": len(model) + 5,
                        }
                    )

                    line_offset += 1
                    session_event_rows.append(
                        {
                            "session_id": session_id,
                            "project_id": PROJECT_ID,
                            "user_id": uid,
                            "agent_id": agent_id,
                            "harness": harness,
                            "line_offset": line_offset,
                            "event_type": "tool_result",
                            "timestamp": event_time,
                            "model": model,
                            "content_preview": "ok" if random.random() >= 0.05 else "error",
                            "content_length": 2,
                        }
                    )

                line_offset += 1
                session_event_rows.append(
                    {
                        "session_id": session_id,
                        "project_id": PROJECT_ID,
                        "user_id": uid,
                        "agent_id": agent_id,
                        "harness": harness,
                        "line_offset": line_offset,
                        "event_type": "session_end",
                        "timestamp": (start_time + timedelta(seconds=30 * num_spans)).strftime("%Y-%m-%d %H:%M:%S"),
                        "model": model,
                        "input_tokens": session_tokens // 2,
                        "output_tokens": session_tokens // 2,
                        "credits": round(session_cost, 4),
                    }
                )

    batch_size = 2000
    print(f"  Inserting {len(session_event_rows)} session events across {len(session_keys)} sessions...")
    for i in range(0, len(session_event_rows), batch_size):
        await insert_session_events(session_event_rows[i : i + batch_size])

    # The dashboard reads session_stats_agg, so rebuild each summary exactly the
    # way the ingest path does after it writes a session's events.
    print(f"  Recomputing {len(session_keys)} session summaries...")
    for session_id, uid, harness in session_keys:
        await refresh_session_summary(session_id, PROJECT_ID, uid, harness)

    print(f"  Done: {len(session_keys)} sessions, {len(session_event_rows)} events")
    return {"sessions": len(session_keys), "events": len(session_event_rows)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    parser = argparse.ArgumentParser(description="Seed exec dashboard test data")
    parser.add_argument(
        "--pg-url",
        default=os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/observal"),
    )
    parser.add_argument(
        "--duckdb-url",
        default=os.environ.get("DUCKDB_ANALYTICS_URL", "duckdb://localhost:8484/observal"),
    )
    parser.add_argument("--duckdb-token", default=os.environ.get("DUCKDB_ANALYTICS_TOKEN", ""))
    parser.add_argument("--clean", action="store_true", help="Delete existing test data first")
    args = parser.parse_args()

    print("=== Exec Dashboard Seed Script ===\n")

    print("[1/2] Seeding PostgreSQL...")
    result = await seed_postgres(args.pg_url, args.clean)

    print("\n[2/2] Seeding the DuckDB analytics store...")
    counts = await seed_analytics(
        args.duckdb_url,
        args.duckdb_token,
        result["user_map"],
        result["agent_map"],
        args.clean,
        result["old_user_ids"],
    )

    print("\n=== Done ===")
    print(f"Users: {len(result['user_map'])}")
    print(f"Agents: {len(result['agent_map'])}")
    print(f"Sessions: {counts['sessions']} ({counts['events']} events)")
    print("\nTo verify: python scripts/verify_exec_dashboard.py --base-url <URL> --token <ADMIN_JWT>")


if __name__ == "__main__":
    asyncio.run(main())
