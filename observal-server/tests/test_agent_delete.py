"""Tests for agent deletion with lazy='raise' relationships.

Verifies that delete_agent eagerly loads Scorecard.penalties and
EvalRun.scorecards so that cascade-delete does not trigger the
lazy='raise' sentinel on those relationships.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.agent import AgentStatus
from models.eval import EvalRun, Scorecard

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role_value: str = "admin"):
    from models.user import UserRole

    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "admin@example.com"
    user.username = "admin"
    user.role = UserRole(role_value)
    user.org_id = None
    return user


def _make_agent(owner_id: uuid.UUID | None = None):
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.name = "test-agent"
    agent.created_by = owner_id or uuid.uuid4()
    agent.co_maintainers = []
    agent.status = AgentStatus.pending
    agent.owner_org_id = None
    agent.team_accesses = []
    return agent


def _make_scorecard(agent_id: uuid.UUID) -> MagicMock:
    sc = MagicMock(spec=Scorecard)
    sc.id = uuid.uuid4()
    sc.agent_id = agent_id
    return sc


def _make_eval_run(agent_id: uuid.UUID) -> MagicMock:
    er = MagicMock(spec=EvalRun)
    er.id = uuid.uuid4()
    er.agent_id = agent_id
    return er


def _build_db(execute_results: list) -> AsyncMock:
    """Build an AsyncSession mock that returns successive results per execute call."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_results)
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    return db


def _scalars_result(items: list) -> MagicMock:
    """Mock execute result whose .scalars().all() returns *items*."""
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _stmt_has_selectinload(stmt) -> bool:
    """Return True if *stmt* has at least one selectinload option.

    SQLAlchemy represents selectinload as a Load object whose context entries
    have strategy == (('lazy', 'selectin'),).
    """
    for opt in getattr(stmt, "_with_options", ()):
        for ctx_entry in getattr(opt, "context", ()):
            if getattr(ctx_entry, "strategy", None) == (("lazy", "selectin"),):
                return True
    return False


# ---------------------------------------------------------------------------
# Test: delete_agent calls db.execute with selectinload for Scorecard.penalties
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_agent_scorecard_query_uses_selectinload_penalties():
    """delete_agent must query Scorecard with selectinload(Scorecard.penalties).

    Without the fix the query omits the eager-load option, which means
    SQLAlchemy will trigger the lazy='raise' sentinel when the ORM cascade
    tries to access scorecard.penalties during db.delete(scorecard).
    """
    from api.routes.agent import delete_agent

    agent = _make_agent()
    scorecard = _make_scorecard(agent.id)

    captured_stmts: list = []

    async def capturing_execute(stmt):
        captured_stmts.append(stmt)
        # feedback, scorecards, eval_runs, downloads — return empty for all except scorecards
        # We return items on the scorecard query (2nd call) and empty for the rest
        return _scalars_result([scorecard] if len(captured_stmts) == 2 else [])

    db = AsyncMock()
    db.execute = capturing_execute
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    user = _make_user()

    with (
        patch("api.routes.agent._load_agent", new=AsyncMock(return_value=agent)),
        patch("api.routes.agent.get_effective_agent_permission", return_value="owner"),
        patch("api.routes.agent.emit_registry_event"),
        patch("api.routes.agent.audit", new=AsyncMock()),
    ):
        result = await delete_agent(agent_id=str(agent.id), db=db, current_user=user)

    assert result == {"deleted": str(agent.id)}

    # The scorecard query is the 2nd execute call (after feedback).
    # It must include a selectinload option for Scorecard.penalties.
    scorecard_stmt = captured_stmts[1]
    assert _stmt_has_selectinload(scorecard_stmt), (
        "Expected selectinload on the Scorecard query but none was found. "
        "The query must use selectinload(Scorecard.penalties) to avoid lazy='raise' "
        "being triggered during cascade-delete."
    )


@pytest.mark.asyncio
async def test_delete_agent_evalrun_query_uses_selectinload_scorecards():
    """delete_agent must query EvalRun with selectinload(EvalRun.scorecards).

    Without the fix the query omits the eager-load option, which means
    SQLAlchemy will trigger the lazy='raise' sentinel when the ORM cascade
    tries to access eval_run.scorecards during db.delete(eval_run).
    """
    from api.routes.agent import delete_agent

    agent = _make_agent()
    eval_run = _make_eval_run(agent.id)

    captured_stmts: list = []

    async def capturing_execute(stmt):
        captured_stmts.append(stmt)
        return _scalars_result([eval_run] if len(captured_stmts) == 3 else [])

    db = AsyncMock()
    db.execute = capturing_execute
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    user = _make_user()

    with (
        patch("api.routes.agent._load_agent", new=AsyncMock(return_value=agent)),
        patch("api.routes.agent.get_effective_agent_permission", return_value="owner"),
        patch("api.routes.agent.emit_registry_event"),
        patch("api.routes.agent.audit", new=AsyncMock()),
    ):
        result = await delete_agent(agent_id=str(agent.id), db=db, current_user=user)

    assert result == {"deleted": str(agent.id)}

    # The eval_run query is the 3rd execute call (feedback, scorecards, eval_runs).
    evalrun_stmt = captured_stmts[2]
    assert _stmt_has_selectinload(evalrun_stmt), (
        "Expected selectinload on the EvalRun query but none was found. "
        "The query must use selectinload(EvalRun.scorecards) to avoid lazy='raise' "
        "being triggered during cascade-delete."
    )


@pytest.mark.asyncio
async def test_delete_agent_deletes_all_returned_records():
    """delete_agent deletes scorecards, eval_runs via ORM and agent+versions via SQL."""
    from api.routes.agent import delete_agent

    agent = _make_agent()
    agent.versions = []  # No versions to simplify
    agent.latest_version_id = None
    scorecard = _make_scorecard(agent.id)
    eval_run = _make_eval_run(agent.id)

    call_count = 0

    async def execute_with_data(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 2:  # scorecard query
            return _scalars_result([scorecard])
        if call_count == 3:  # eval_run query
            return _scalars_result([eval_run])
        return _scalars_result([])

    db = AsyncMock()
    db.execute = execute_with_data
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    user = _make_user()

    with (
        patch("api.routes.agent._load_agent", new=AsyncMock(return_value=agent)),
        patch("api.routes.agent.get_effective_agent_permission", return_value="owner"),
        patch("api.routes.agent.emit_registry_event"),
        patch("api.routes.agent.audit", new=AsyncMock()),
    ):
        result = await delete_agent(agent_id=str(agent.id), db=db, current_user=user)

    assert result == {"deleted": str(agent.id)}

    # Scorecards and eval_runs are deleted via ORM db.delete()
    deleted_objects = [c.args[0] for c in db.delete.call_args_list]
    assert scorecard in deleted_objects, "Scorecard was not deleted"
    assert eval_run in deleted_objects, "EvalRun was not deleted"
    # Agent + versions deleted via SQL DELETE (db.execute), commit confirms completion
    db.commit.assert_called_once()
