#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Seed a completed insight report with suggestions for testing self-learn.

Usage:
    docker exec docker-observal-api-1 /app/.venv/bin/python /app/scripts/seed_insight_report.py

Or locally (with server running):
    python scripts/seed_insight_report.py
"""

import asyncio
import sys

sys.path.insert(0, "/app")


async def main():
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from database import async_session
    from models.agent import Agent
    from models.insight_report import InsightReport, InsightReportStatus

    async with async_session() as db:
        # Find any approved agent
        result = await db.execute(select(Agent).where(Agent.status == "approved").limit(1))
        agent = result.scalar_one_or_none()

        if not agent:
            print("ERROR: No approved agent found. Create one first:")
            print("  - Go to Builder in the UI and create + approve an agent")
            print("  - Or use: observal agent create ...")
            return

        # Find the admin user (triggered_by)
        from models.user import User, UserRole

        user_result = await db.execute(select(User).where(User.role == UserRole.admin).limit(1))
        admin = user_result.scalar_one_or_none()

        now = datetime.now(UTC)
        report = InsightReport(
            agent_id=agent.id,
            triggered_by=admin.id if admin else None,
            status=InsightReportStatus.completed,
            period_start=now - timedelta(days=14),
            period_end=now,
            started_at=now - timedelta(minutes=5),
            completed_at=now,
            sessions_analyzed=12,
            report_version=3,
            metrics={
                "rich": {
                    "total_sessions": 12,
                    "total_messages": 156,
                    "active_hours": 8.5,
                    "days_active": 7,
                    "lines_added": 1243,
                    "lines_removed": 387,
                    "files_modified": 45,
                    "git_commits": 8,
                    "git_pushes": 3,
                    "tool_errors": 14,
                    "interruptions": 2,
                    "subagent_sessions": 3,
                    "mcp_sessions": 0,
                    "total_cost_usd": 4.72,
                    "total_input_tokens": 892000,
                    "total_output_tokens": 156000,
                    "total_cache_read_tokens": 2100000,
                    "total_cache_write_tokens": 450000,
                    "top_tools": [
                        ["Read", 234],
                        ["Edit", 189],
                        ["Bash", 156],
                        ["Write", 78],
                        ["Grep", 45],
                    ],
                    "top_languages": [
                        ["Python", 67],
                        ["TypeScript", 34],
                        ["YAML", 12],
                    ],
                    "tool_error_categories": {
                        "command_failed": 6,
                        "edit_failed": 4,
                        "file_not_found": 3,
                        "permission_denied": 1,
                    },
                },
                "overview": {"total_sessions": 12, "unique_users": 1},
            },
            narrative={
                "at_a_glance": {
                    "health": "healthy",
                    "whats_working": "You're productive with multi-file refactors and test generation. The agent handles complex TypeScript and Python changes confidently.",
                    "whats_hindering": "Tool errors on edit operations (33% of all errors) suggest the agent often targets stale file content. You also repeatedly remind it to run tests.",
                    "quick_win": "Add 'always run tests before committing' to your system prompt, you've said this in 8 of 12 sessions.",
                    "ambitious_workflows": "With parallel subagents, you could have one agent write code while another continuously runs the test suite, catching regressions in real-time.",
                },
                "what_they_work_on": {
                    "areas": [
                        {
                            "name": "API Routes",
                            "sessions": 5,
                            "description": "You build and refactor FastAPI endpoints, adding validation and error handling.",
                        },
                        {
                            "name": "Test Suite",
                            "sessions": 4,
                            "description": "You generate and fix pytest tests, often using the agent to write comprehensive test cases.",
                        },
                        {
                            "name": "Frontend Components",
                            "sessions": 3,
                            "description": "You build React components with TypeScript, focusing on data tables and forms.",
                        },
                    ]
                },
                "interaction_style": {
                    "narrative": "You're a **directive communicator** who gives clear, specific instructions. You rarely iterate; instead, you provide complete context upfront and expect the agent to get it right in one shot.\n\nWhen things go wrong, you **redirect sharply** rather than gradually correcting. Your repeated instructions about testing suggest frustration with having to remind the agent of basics.",
                    "key_pattern": "Upfront context, single-shot execution, sharp redirects on failure",
                },
                "usage_patterns": {
                    "narrative": "You use the agent in focused 30-45 minute sessions, typically 2-3 per day. Most sessions involve multi-file changes.",
                    "session_profile": {
                        "avg_duration_minutes": 38,
                        "avg_tool_calls": 45,
                        "session_type": "implementation",
                    },
                    "tool_distribution": [
                        {"tool": "Read", "calls": 234, "error_rate": 0},
                        {"tool": "Edit", "calls": 189, "error_rate": 7.2},
                        {"tool": "Bash", "calls": 156, "error_rate": 3.8},
                        {"tool": "Write", "calls": 78, "error_rate": 0},
                    ],
                },
                "what_works": {
                    "intro": "The agent excels at multi-file refactors and comprehensive test generation.",
                    "strengths": [
                        {
                            "title": "Multi-file coordination",
                            "description": "Successfully coordinated edits across 45 files with zero conflicts in a single session.",
                        },
                        {
                            "title": "Test comprehensiveness",
                            "description": "Generated test suites that caught 3 real bugs you hadn't noticed, including an edge case in auth token expiry.",
                        },
                    ],
                },
                "friction_analysis": {
                    "intro": "Most friction comes from stale file content and forgotten conventions.",
                    "categories": [
                        {
                            "title": "Stale file edits",
                            "severity": "high",
                            "description": "The agent attempts edits on outdated file content, causing failures.",
                            "evidence": "14 tool errors, 6 from edit_failed",
                            "impact": "You waste 2-3 minutes per session re-reading files.",
                        },
                        {
                            "title": "Forgotten conventions",
                            "severity": "medium",
                            "description": "You repeatedly tell the agent to run tests and use ruff format.",
                            "evidence": "Mentioned in 8/12 sessions",
                            "impact": "Cognitive load of remembering to remind.",
                        },
                    ],
                },
                "suggestions": {
                    "config_additions": [
                        {
                            "addition": "Always run the test suite (pytest) before committing any changes.",
                            "why": "You reminded the agent to test in 8 of 12 sessions",
                            "where": "system_prompt",
                        },
                        {
                            "addition": "After editing a file, re-read it to verify the edit applied correctly before moving on.",
                            "why": "33% of tool errors were from stale edits",
                            "where": "system_prompt",
                        },
                        {
                            "addition": "Run ruff check and ruff format on all modified Python files before finishing.",
                            "why": "Repeated instruction in 6 sessions",
                            "where": "AGENTS.md",
                        },
                        {
                            "addition": "When working on FastAPI routes, always include input validation with Pydantic models.",
                            "why": "You corrected missing validation 4 times",
                            "where": "system_prompt",
                        },
                    ],
                    "features_to_try": [
                        {
                            "feature": "Custom skill",
                            "one_liner": "PR review workflow that checks tests, lint, and security",
                            "why_for_you": "You do PR reviews in 40% of sessions",
                            "example": "---\nname: pr-review\ndescription: Review PR for correctness, tests, and security\ntrigger: /review\n---\n\n1. Read the git diff\n2. Check all modified files have tests\n3. Run ruff check on changed Python files\n4. Look for security issues (SQL injection, path traversal)\n5. Summarize findings with severity ratings",
                        },
                        {
                            "feature": "Lifecycle hook",
                            "one_liner": "Pre-commit validation gate",
                            "why_for_you": "Catches forgotten test runs before they reach CI",
                            "example": "# Hook: before git commit\npytest --tb=short -q\nruff check .",
                        },
                    ],
                    "usage_patterns": [
                        {
                            "title": "Structured debugging",
                            "suggestion": "Start debugging sessions with reproduction",
                            "detail": "When debugging, ask the agent to reproduce the issue first before suggesting fixes. This prevents guesswork.",
                            "copyable_prompt": "Reproduce this bug by running the failing test in isolation, show me the full traceback, then identify the root cause before suggesting any fix.",
                        },
                        {
                            "title": "Batch file operations",
                            "suggestion": "Group related file changes",
                            "detail": "Instead of editing files one by one, describe the full scope upfront so the agent can plan.",
                            "copyable_prompt": "I need to add input validation to all POST endpoints in api/routes/. List the files first, then edit them all with Pydantic model validation.",
                        },
                    ],
                },
                "on_the_horizon": {
                    "intro": "Your workflow is already agent-native. Here's what becomes possible with more capable models.",
                    "opportunities": [
                        {
                            "title": "Parallel test-driven development",
                            "whats_possible": "Run a subagent that continuously executes your test suite while you code. It catches regressions within seconds of introduction.",
                            "how_to_try": "Use the Agent tool to spawn a test-watcher subagent.",
                            "copyable_prompt": "Spawn a subagent that watches for file changes and runs pytest on modified test files. Report failures immediately.",
                        },
                    ],
                },
                "usage_cost_analysis": {
                    "summary": "Your cost efficiency is excellent: high cache hit rate keeps per-session cost under $0.40.",
                    "metrics": {"total_cost_usd": 4.72, "cost_per_session": 0.39, "cache_efficiency_pct": 70},
                    "opportunities": [],
                },
                "fun_ending": {
                    "headline": "You asked the agent to 'test something small' and it wrote 51 tests covering edge cases you'd never considered.",
                    "detail": "The auth token expiry bug it found would have caused a production incident.",
                },
            },
            aggregated_data={
                "facets_summary": {
                    "goal_categories": [["implementation", 5], ["testing", 4], ["debugging", 3]],
                    "outcomes": {"completed": 9, "partially_completed": 2, "abandoned": 1},
                    "satisfaction": {"high": 7, "medium": 4, "low": 1},
                    "friction_types": [["stale_edit", 6], ["forgotten_instruction", 4], ["wrong_approach", 2]],
                },
            },
        )
        db.add(report)
        await db.commit()

        print(f"✓ Created insight report: {report.id}")
        print(f"  Agent: {agent.name} ({agent.id})")
        print("  Status: completed")
        print("  Sessions: 12")
        print("  Suggestions: 4 config_additions, 2 features_to_try, 2 usage_patterns")
        print(f"\n  → Go to: http://localhost:3000/insights/{report.id}")
        print("  → Click 'Apply Suggestions' to test self-learn!")


if __name__ == "__main__":
    asyncio.run(main())
