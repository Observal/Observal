# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Build per-user work profiles from session telemetry.

A profile answers "what does this person actually work on?" using only
metadata — file extensions, tool names, MCP server names, harnesses, error
categories. Prompt and transcript text is never read, so the profile is safe
to compute for every user regardless of the org's ``trace_privacy`` setting.

ClickHouse access pattern matters here. ``session_stats_agg`` has a bloom
filter on ``user_id``; ``session_events`` does **not** (only session_id,
project_id, event_type, line_hash). So we resolve user -> session ids from the
aggregate table first, then fetch events by session id. Filtering
``session_events`` on ``user_id`` directly would scan whole partitions.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from loguru import logger as optic
from sqlalchemy import select

from models.user_profile import UserWorkProfile
from services.clickhouse import _query

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

# How far back a profile looks, and how many sessions it will consider.
DEFAULT_PROFILE_DAYS = 60
MAX_PROFILE_SESSIONS = 300
# Session ids travel to ClickHouse in the HTTP query string, so the id-array
# queries use a tighter cap than the session listing to keep the URI sane.
MAX_ID_ARRAY = 150

# Tool/server name fragments mapped to a coarse work topic. Deliberately a
# small, readable heuristic rather than a classifier: it feeds a lexical
# search, so precision matters more than coverage. Tune here, nowhere else.
TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "databases": ("postgres", "mysql", "sqlite", "mongo", "redis", "sql", "prisma", "database", "db"),
    "frontend": ("react", "vue", "svelte", "css", "tailwind", "browser", "figma", "ui"),
    "infrastructure": ("docker", "kubernetes", "k8s", "terraform", "aws", "gcp", "azure", "helm", "deploy"),
    "version-control": ("git", "github", "gitlab", "pr", "commit", "branch"),
    "testing": ("pytest", "jest", "vitest", "playwright", "test", "coverage"),
    "observability": ("grafana", "prometheus", "sentry", "datadog", "log", "trace", "metric"),
    "security": ("auth", "oauth", "saml", "secret", "vault", "crypto", "vulnerab"),
    "data-analytics": ("pandas", "spark", "airflow", "dbt", "warehouse", "analytic"),
    "productivity": ("slack", "notion", "jira", "linear", "calendar", "email"),
}


@dataclass
class WorkProfile:
    """A user's derived interests. All fields are ordered most-used first."""

    languages: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    harnesses: list[str] = field(default_factory=list)
    error_categories: list[str] = field(default_factory=list)
    session_count: int = 0

    def to_dict(self) -> dict:
        return {
            "languages": self.languages,
            "tools": self.tools,
            "mcp_servers": self.mcp_servers,
            "topics": self.topics,
            "harnesses": self.harnesses,
            "error_categories": self.error_categories,
        }

    @classmethod
    def from_dict(cls, data: dict, session_count: int = 0) -> WorkProfile:
        data = data or {}
        return cls(
            languages=list(data.get("languages") or []),
            tools=list(data.get("tools") or []),
            mcp_servers=list(data.get("mcp_servers") or []),
            topics=list(data.get("topics") or []),
            harnesses=list(data.get("harnesses") or []),
            error_categories=list(data.get("error_categories") or []),
            session_count=session_count,
        )

    def is_empty(self) -> bool:
        return not (self.languages or self.tools or self.mcp_servers or self.topics)

    def search_signals(self) -> str:
        """Flatten the profile into a search string for the recommender."""
        from services.registry_recommender import build_signal_query

        return build_signal_query(
            self.topics,
            self.mcp_servers,
            self.languages,
            self.tools[:10],
            self.error_categories,
        )


def _mcp_server_name(tool_name: str) -> str | None:
    """Extract the server from an ``mcp__<server>__<tool>`` tool name."""
    if not tool_name.startswith("mcp__"):
        return None
    parts = tool_name.split("__")
    return parts[1] if len(parts) >= 2 and parts[1] else None


def _topics_for(terms: list[str]) -> Counter:
    """Bucket assorted terms into coarse topics."""
    found: Counter = Counter()
    for term in terms:
        lowered = term.lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                found[topic] += 1
    return found


async def _ch_rows(sql: str, params: dict) -> list[dict]:
    try:
        response = await _query(sql, params)
        response.raise_for_status()
        return response.json().get("data", [])
    except Exception as e:
        optic.warning("user_profile: clickhouse query failed: {}", e)
        return []


# Session ids originate from client-supplied ingest payloads, so they are
# untrusted. Everything a real harness emits is a uuid or a slug-ish id, and
# this is deliberately narrower than that.
_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _id_array(session_ids: list[str]) -> str:
    """Render session ids as a ClickHouse array literal.

    Parameters travel as HTTP query values, so the array has to arrive
    pre-formatted rather than bound. Ids are therefore *rejected* unless they
    match a strict allowlist — not escaped, and not merely quote-stripped.
    Stripping only quotes would still admit a trailing backslash, which
    ClickHouse treats as an escape and which could swallow the closing quote
    of the literal.
    """
    safe = [sid for sid in session_ids if _SAFE_SESSION_ID.match(sid or "")]
    dropped = len(session_ids) - len(safe)
    if dropped:
        optic.warning("user_profile: dropped {} session id(s) with unexpected characters", dropped)
    return "[" + ",".join(f"'{sid}'" for sid in safe[:MAX_ID_ARRAY]) + "]"


async def users_with_recent_activity(days: int = DEFAULT_PROFILE_DAYS) -> set[tuple[str, str]] | None:
    """``(project_id, user_id)`` pairs that have a session in the window.

    One query for the whole instance, so a caller sweeping every user can
    skip the inactive ones instead of paying a ClickHouse round trip each to
    discover they have nothing. ``session_stats_agg`` is the aggregate table,
    so this reads far less than the per-user profile queries it saves.

    Returns ``None`` — distinct from an empty set — when the lookup fails, so
    callers can fall back to sweeping everyone rather than silently deciding
    that nobody is active.
    """
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        response = await _query(
            """
            SELECT DISTINCT project_id, user_id
            FROM session_stats_agg FINAL
            WHERE last_event_time >= {since:String}
              AND user_id != ''
            FORMAT JSON
            """,
            {"param_since": since},
        )
        response.raise_for_status()
        rows = response.json().get("data", [])
    except Exception:
        optic.warning("user_profile: active-user lookup failed")
        return None

    return {(str(r.get("project_id") or ""), str(r.get("user_id") or "")) for r in rows}


async def build_profile(
    user_id: uuid.UUID,
    project_id: str,
    days: int = DEFAULT_PROFILE_DAYS,
) -> WorkProfile:
    """Compute a fresh profile for one user from their own sessions."""
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    # Step 1: user -> sessions, via the table that indexes user_id.
    session_rows = await _ch_rows(
        """
        SELECT session_id, any_value(harness) AS harness
        FROM session_stats_agg FINAL
        WHERE user_id = {uid:String}
          AND project_id = {pid:String}
          AND last_event_time >= {since:String}
        GROUP BY session_id
        ORDER BY max(last_event_time) DESC
        LIMIT {limit:UInt32}
        FORMAT JSON
        """,
        {
            "param_uid": str(user_id),
            "param_pid": project_id,
            "param_since": since,
            "param_limit": MAX_PROFILE_SESSIONS,
        },
    )
    if not session_rows:
        return WorkProfile()

    session_ids = [row["session_id"] for row in session_rows if row.get("session_id")]
    harnesses = Counter(row["harness"] for row in session_rows if row.get("harness"))
    if not session_ids:
        return WorkProfile()

    # Step 2: sessions -> tool usage, keyed on the indexed session_id column.
    tool_rows = await _ch_rows(
        """
        SELECT tool_name, count() AS uses
        FROM session_events
        WHERE session_id IN ({ids:Array(String)})
          AND tool_name IS NOT NULL
          AND tool_name != ''
        GROUP BY tool_name
        ORDER BY uses DESC
        LIMIT 200
        FORMAT JSON
        """,
        {"param_ids": _id_array(session_ids)},
    )

    tools: Counter = Counter()
    mcp_servers: Counter = Counter()
    for row in tool_rows:
        name = str(row.get("tool_name") or "")
        uses = int(row.get("uses") or 0)
        if not name:
            continue
        server = _mcp_server_name(name)
        if server:
            mcp_servers[server] += uses
        else:
            tools[name] += uses

    # Step 3: file extensions -> languages, from tool-call previews.
    languages = await _languages_for_sessions(session_ids)

    topic_terms = list(mcp_servers) + list(tools) + list(languages)
    topics = _topics_for(topic_terms)

    return WorkProfile(
        languages=[name for name, _ in languages.most_common(8)],
        tools=[name for name, _ in tools.most_common(15)],
        mcp_servers=[name for name, _ in mcp_servers.most_common(10)],
        topics=[name for name, _ in topics.most_common(6)],
        harnesses=[name for name, _ in harnesses.most_common(5)],
        error_categories=[],
        session_count=len(session_ids),
    )


async def _languages_for_sessions(session_ids: list[str]) -> Counter:
    """Infer languages from file paths mentioned in tool-call previews.

    ``content_preview`` is a short, already-truncated summary written at
    ingest — this does not read full transcripts.
    """
    rows = await _ch_rows(
        """
        SELECT content_preview
        FROM session_events
        WHERE session_id IN ({ids:Array(String)})
          AND event_type = 'tool_call'
          AND content_preview != ''
        LIMIT 5000
        FORMAT JSON
        """,
        {"param_ids": _id_array(session_ids)},
    )

    # Imported lazily: `services.insights` pulls in LiteLLM at package import
    # time, and a profile rebuild should not pay for that.
    from services.insights.session_meta_extractor import EXTENSION_TO_LANGUAGE

    languages: Counter = Counter()
    for row in rows:
        preview = str(row.get("content_preview") or "")
        for extension, language in EXTENSION_TO_LANGUAGE.items():
            if extension in preview:
                languages[language] += 1
    return languages


async def get_or_build_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    project_id: str,
    max_age_hours: int = 24,
    force: bool = False,
) -> WorkProfile:
    """Return a cached profile, recomputing it when stale.

    Recomputation touches ClickHouse, so the cache is what keeps the
    recommendations endpoint cheap enough to call on page load.
    """
    existing = (
        await db.execute(select(UserWorkProfile).where(UserWorkProfile.user_id == user_id))
    ).scalar_one_or_none()

    if existing and not force:
        computed_at = existing.computed_at
        if computed_at is not None:
            if computed_at.tzinfo is None:
                computed_at = computed_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - computed_at < timedelta(hours=max_age_hours):
                return WorkProfile.from_dict(existing.profile, existing.session_count)

    profile = await build_profile(user_id, project_id)
    await _persist(db, user_id, profile, existing)
    return profile


async def _persist(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile: WorkProfile,
    existing: UserWorkProfile | None,
) -> None:
    try:
        if existing:
            existing.profile = profile.to_dict()
            existing.session_count = profile.session_count
            existing.computed_at = datetime.now(UTC)
        else:
            db.add(
                UserWorkProfile(
                    user_id=user_id,
                    profile=profile.to_dict(),
                    session_count=profile.session_count,
                    computed_at=datetime.now(UTC),
                )
            )
        await db.commit()
    except Exception as e:
        # A cache write failure must not break the caller's request.
        await db.rollback()
        optic.warning("user_profile: persist failed for {}: {}", user_id, e)
