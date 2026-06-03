# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Version impact analysis for insight reports.

Cross-user layer correlation: groups sessions by layer_hash, compares
metrics between groups, and surfaces anonymized patterns about which
configurations lead to better outcomes.

Key concepts:
- "canonical": layer state matches lockfile integrity (no user modifications)
- "dirty": user modified files after install (drift detected)
- Groups are compared by metrics, not by user identity
"""

from __future__ import annotations

import json

import structlog

from ._deps import get_query

logger = structlog.get_logger(__name__)


async def detect_layer_groups(
    agent_id: str,
    period_start: str,
    period_end: str,
    agent_name: str = "",
) -> list[dict]:
    """Group sessions by layer_hash and compute metrics per group.

    Returns groups ordered by session count (largest first):
    [
        {
            "layer_hash": "abc123...",
            "sessions": 45,
            "users": 12,
            "avg_prompts": 8.2,
            "avg_tool_calls": 15.4,
            "avg_duration_seconds": 420.0,
            "avg_cost": 0.12,
            "avg_tokens": 50000,
            "tool_error_rate": 0.05,
            "success_proxy": 0.82,
        },
        ...
    ]
    """
    query = get_query()

    sql = """
        SELECT
            layer_hash,
            count() AS sessions,
            uniq(user_id) AS users,
            avg(prompt_count) AS avg_prompts,
            avg(tool_call_count) AS avg_tool_calls,
            avg(toFloat64(last_event_time - first_event_time)) AS avg_duration_seconds,
            sum(total_credits) / count() AS avg_cost,
            sum(input_tokens + output_tokens) / count() AS avg_tokens,
            -- Tool error proxy: sessions with high tool_result vs tool_call ratio
            -- (more results than calls = retries/errors)
            countIf(tool_result_count > tool_call_count * 1.5) / count() AS tool_error_rate,
            -- Success proxy: sessions that complete (have a stop event) with reasonable duration
            countIf(event_count > 5 AND prompt_count >= 1) / count() AS success_proxy
        FROM session_stats_agg FINAL
        WHERE (agent_id = {agent_id:String} OR agent_id = {agent_name:String})
          AND last_event_time >= {t_start:String}
          AND last_event_time <= {t_end:String}
          AND layer_hash != ''
        GROUP BY layer_hash
        HAVING sessions >= 3
        ORDER BY sessions DESC
        LIMIT 20
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_agent_name": agent_name,
        "param_t_start": period_start,
        "param_t_end": period_end,
    }

    try:
        r = await query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception as e:
        logger.warning("layer_groups_query_failed", error=str(e))
        return []

    return [
        {
            "layer_hash": row["layer_hash"],
            "sessions": int(row.get("sessions", 0)),
            "users": int(row.get("users", 0)),
            "avg_prompts": round(float(row.get("avg_prompts", 0)), 1),
            "avg_tool_calls": round(float(row.get("avg_tool_calls", 0)), 1),
            "avg_duration_seconds": round(float(row.get("avg_duration_seconds", 0)), 0),
            "avg_cost": round(float(row.get("avg_cost", 0)), 4),
            "avg_tokens": int(float(row.get("avg_tokens", 0))),
            "tool_error_rate": round(float(row.get("tool_error_rate", 0)), 3),
            "success_proxy": round(float(row.get("success_proxy", 0)), 3),
        }
        for row in rows
    ]


async def fetch_layer_snapshots_for_groups(
    project_id: str,
    layer_hashes: list[str],
) -> dict[str, dict]:
    """Fetch stored layer snapshots for a list of hashes.

    Returns {hash: snapshot_content} for snapshots that exist.
    """
    if not layer_hashes:
        return {}

    query = get_query()

    # Validate hashes are strictly hex (prevent injection into Array literal)
    import re

    hex_re = re.compile(r"^[0-9a-fA-F]+$")
    safe_hashes = [h for h in layer_hashes if hex_re.match(h)]
    if not safe_hashes:
        return {}

    sql = """
        SELECT hash, content
        FROM layer_snapshots FINAL
        WHERE project_id = {project_id:String}
          AND hash IN ({hashes:Array(String)})
        FORMAT JSON
    """
    params = {
        "param_project_id": project_id,
        "param_hashes": "[" + ",".join(f"'{h}'" for h in safe_hashes) + "]",
    }

    try:
        r = await query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])
        return {row["hash"]: json.loads(row["content"]) for row in rows}
    except Exception as e:
        logger.warning("layer_snapshots_fetch_failed", error=str(e))
        return {}


def diff_snapshots(snap_a: dict, snap_b: dict) -> dict:
    """Diff two layer snapshots to find what's different.

    Returns a summary of differences (not full content, to keep prompt size sane).
    """
    files_a: dict[str, str] = {}
    files_b: dict[str, str] = {}

    # Flatten both snapshots to {ide/path: hash}
    for ide_name, files in (snap_a.get("ides") or {}).items():
        for f in files:
            files_a[f"{ide_name}/{f['path']}"] = f.get("hash", "")

    for ide_name, files in (snap_b.get("ides") or {}).items():
        for f in files:
            files_b[f"{ide_name}/{f['path']}"] = f.get("hash", "")

    paths_a = set(files_a.keys())
    paths_b = set(files_b.keys())

    return {
        "added": sorted(paths_b - paths_a),
        "removed": sorted(paths_a - paths_b),
        "modified": sorted(p for p in paths_a & paths_b if files_a[p] != files_b[p]),
    }


def extract_content_summary(snapshot: dict, max_chars: int = 1500) -> str:
    """Extract a brief content summary from a snapshot for LLM context.

    Focuses on rules/agents/skills content (the things that shape behavior).
    Anonymized: no user paths, no personal info.
    Only called when significant performance gap detected.
    """
    lines: list[str] = []
    char_count = 0

    for ide_name, files in (snapshot.get("ides") or {}).items():
        for f in files:
            path = f.get("path", "")
            content = f.get("content", "")
            if not content:
                continue

            # Only include behavioral files (rules, agents, skills)
            if not any(x in path for x in ("CLAUDE.md", "AGENTS.md", "agents/", "skills/", "rules/")):
                continue

            # Truncate individual file content
            snippet = content[:500] if len(content) > 500 else content
            entry = f"[{ide_name}:{path}]\n{snippet}"

            if char_count + len(entry) > max_chars:
                break
            lines.append(entry)
            char_count += len(entry)

    return "\n---\n".join(lines) if lines else "(no behavioral content captured)"


async def build_version_impact_data(
    agent_id: str,
    period_start: str,
    period_end: str,
    agent_name: str = "",
    project_id: str = "default",
) -> dict | None:
    """Build the complete version impact data block for the insight report.

    Cross-user analysis: compares layer groups and surfaces anonymized patterns.
    Returns None if insufficient data or no significant difference between groups.

    Only fetches layer snapshot content when metrics show >= 20% difference
    in success_proxy or tool_error_rate between best and worst groups.
    This avoids flooding LLM context with huge snapshots when configs don't matter.
    """
    groups = await detect_layer_groups(
        agent_id=agent_id,
        period_start=period_start,
        period_end=period_end,
        agent_name=agent_name,
    )

    if len(groups) < 2:
        return None

    # Check for significant difference before fetching snapshots
    best_success = max(g["success_proxy"] for g in groups)
    worst_success = min(g["success_proxy"] for g in groups)
    best_error = min(g["tool_error_rate"] for g in groups)
    worst_error = max(g["tool_error_rate"] for g in groups)

    success_gap = best_success - worst_success
    error_gap = worst_error - best_error

    # Threshold: at least 20% absolute gap in success or 15% in error rate
    significant = success_gap >= 0.20 or error_gap >= 0.15

    if not significant:
        # Return lightweight summary (no snapshot content, saves context)
        return {
            "group_count": len(groups),
            "total_sessions": sum(g["sessions"] for g in groups),
            "total_users": sum(g["users"] for g in groups),
            "significant": False,
            "groups": [
                {
                    "layer_hash": g["layer_hash"],
                    "sessions": g["sessions"],
                    "users": g["users"],
                    "success_proxy": g["success_proxy"],
                    "tool_error_rate": g["tool_error_rate"],
                }
                for g in groups[:5]
            ],
            "finding": "No significant performance difference between configurations.",
        }

    # Significant gap found: fetch snapshots to explain WHY
    top_hashes = [g["layer_hash"] for g in groups[:5]]
    snapshots = await fetch_layer_snapshots_for_groups(project_id, top_hashes)

    # Find best and worst performing groups
    groups_with_data = [g for g in groups if g["layer_hash"] in snapshots]
    if len(groups_with_data) < 2:
        return None

    # Sort by success_proxy (higher = better)
    sorted_by_success = sorted(groups_with_data, key=lambda g: g["success_proxy"], reverse=True)
    best_group = sorted_by_success[0]
    worst_group = sorted_by_success[-1]

    # Diff the best vs worst configs
    best_snap = snapshots.get(best_group["layer_hash"], {})
    worst_snap = snapshots.get(worst_group["layer_hash"], {})
    config_diff = diff_snapshots(best_snap, worst_snap)

    # Extract anonymized content summaries
    best_summary = extract_content_summary(best_snap)
    worst_summary = extract_content_summary(worst_snap)

    # Extract version pins if available
    best_versions = best_snap.get("pinned_versions", {})
    worst_versions = worst_snap.get("pinned_versions", {})

    return {
        "group_count": len(groups),
        "total_sessions": sum(g["sessions"] for g in groups),
        "total_users": sum(g["users"] for g in groups),
        "significant": True,
        "success_gap_pct": round(success_gap * 100, 1),
        "error_gap_pct": round(error_gap * 100, 1),
        "groups": [
            {
                "layer_hash": g["layer_hash"],
                "sessions": g["sessions"],
                "users": g["users"],
                "success_proxy": g["success_proxy"],
                "tool_error_rate": g["tool_error_rate"],
                "avg_cost": g["avg_cost"],
                "avg_duration_seconds": g["avg_duration_seconds"],
                "is_canonical": snapshots.get(g["layer_hash"], {}).get("drift", {}).get("is_canonical", None),
            }
            for g in groups_with_data
        ],
        "best_config": {
            "layer_hash": best_group["layer_hash"],
            "metrics": best_group,
            "content_summary": best_summary,
            "versions": best_versions,
        },
        "worst_config": {
            "layer_hash": worst_group["layer_hash"],
            "metrics": worst_group,
            "content_summary": worst_summary,
            "versions": worst_versions,
        },
        "config_diff_best_vs_worst": config_diff,
    }
