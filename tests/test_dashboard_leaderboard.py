# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from api.routes.dashboard import agent_leaderboard, component_leaderboard, top_agents
from models.user import User, UserRole

_LISTING_TABLES = ["mcp_listings", "skill_listings", "hook_listings", "prompt_listings", "sandbox_listings"]


class _EmptyResult:
    def all(self):
        return []

    def scalars(self):
        return self


class _CaptureDb:
    def __init__(self):
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _EmptyResult()


def _sql(stmt) -> str:
    """Compile a statement to a single-line SQL string with bind values inlined."""
    return " ".join(str(stmt.compile(compile_kwargs={"literal_binds": True})).split())


def _caller(role: UserRole = UserRole.user) -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.role = role
    return user


def _membership_predicate(table: str, user: User) -> str:
    """The correlated EXISTS that gates team-private rows on the caller's own membership."""
    return (
        "EXISTS (SELECT team_memberships.id FROM team_memberships "
        f"WHERE team_memberships.team_id = {table}.team_id "
        f"AND team_memberships.user_id = '{user.id.hex}')"
    )


def _download_queries(db: _CaptureDb) -> list:
    return [stmt for stmt in db.statements if "agent_download_records" in _sql(stmt)]


# ── Deleted-agent exclusion ───────────────────────────────────────────────────


async def test_agent_leaderboard_excludes_deleted_agents():
    db = _CaptureDb()

    await agent_leaderboard(window="all", limit=20, user=None, db=db, current_user=None)

    assert db.statements
    assert all("agents.deleted_at IS NULL" in _sql(stmt) for stmt in db.statements)


async def test_top_agents_excludes_deleted_agents():
    db = _CaptureDb()

    await top_agents(limit=6, db=db, current_user=None)

    assert db.statements
    assert "agents.deleted_at IS NULL" in _sql(db.statements[0])


async def test_component_leaderboard_ignores_downloads_from_deleted_agents():
    db = _CaptureDb()

    await component_leaderboard(window="all", limit=20, user=None, db=db, current_user=None)

    download_queries = _download_queries(db)
    assert len(download_queries) == 5
    assert all("agents.deleted_at IS NULL" in _sql(stmt) for stmt in download_queries)


# ── Visibility scoping (Feature 3: team_id is the only privacy axis) ──────────


async def test_top_agents_hides_team_private_agents_from_anonymous_callers():
    db = _CaptureDb()

    await top_agents(limit=6, db=db, current_user=None)

    sql = _sql(db.statements[0])
    assert "agents.is_private = false" in sql
    assert "agents.is_private = true" not in sql
    assert "team_memberships" not in sql


async def test_top_agents_gates_team_private_agents_on_caller_membership():
    caller = _caller()
    outsider = _caller()
    db = _CaptureDb()

    await top_agents(limit=6, db=db, current_user=caller)

    sql = _sql(db.statements[0])
    assert _membership_predicate("agents", caller) in sql
    assert outsider.id.hex not in sql


async def test_top_agents_does_not_restrict_visibility_for_reviewers():
    db = _CaptureDb()

    await top_agents(limit=6, db=db, current_user=_caller(role=UserRole.reviewer))

    sql = _sql(db.statements[0])
    assert "agents.is_private =" not in sql
    assert "team_memberships" not in sql


async def test_agent_leaderboard_hides_team_private_agents_from_anonymous_callers():
    db = _CaptureDb()

    await agent_leaderboard(window="all", limit=20, user=None, db=db, current_user=None)

    assert db.statements
    for stmt in db.statements:
        sql = _sql(stmt)
        assert "agents.is_private = false" in sql
        assert "team_memberships" not in sql


async def test_agent_leaderboard_gates_team_private_agents_on_caller_membership():
    caller = _caller()
    outsider = _caller()
    db = _CaptureDb()

    await agent_leaderboard(window="all", limit=20, user=None, db=db, current_user=caller)

    assert db.statements
    for stmt in db.statements:
        sql = _sql(stmt)
        assert _membership_predicate("agents", caller) in sql
        assert outsider.id.hex not in sql


async def test_component_leaderboard_hides_team_private_rows_from_anonymous_callers():
    db = _CaptureDb()

    await component_leaderboard(window="all", limit=20, user=None, db=db, current_user=None)

    assert all("team_memberships" not in _sql(stmt) for stmt in db.statements)
    for table, stmt in zip(_LISTING_TABLES, _download_queries(db), strict=True):
        sql = _sql(stmt)
        assert "agents.is_private = false" in sql
        assert f"{table}.is_private = false" in sql
        assert f"{table}.is_private = true" not in sql


async def test_component_leaderboard_gates_team_private_rows_on_caller_membership():
    caller = _caller()
    outsider = _caller()
    db = _CaptureDb()

    await component_leaderboard(window="all", limit=20, user=None, db=db, current_user=caller)

    for table, stmt in zip(_LISTING_TABLES, _download_queries(db), strict=True):
        sql = _sql(stmt)
        assert _membership_predicate("agents", caller) in sql
        assert _membership_predicate(table, caller) in sql
        assert outsider.id.hex not in sql
