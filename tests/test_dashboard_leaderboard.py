# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from api.routes.dashboard import agent_leaderboard, component_leaderboard, top_agents


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
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


async def test_agent_leaderboard_excludes_deleted_agents():
    db = _CaptureDb()

    await agent_leaderboard.__wrapped__(window="all", limit=20, user=None, db=db)

    assert db.statements
    assert all("agents.deleted_at IS NULL" in _sql(stmt) for stmt in db.statements)


async def test_top_agents_excludes_deleted_agents():
    db = _CaptureDb()

    await top_agents.__wrapped__(limit=6, db=db)

    assert db.statements
    assert "agents.deleted_at IS NULL" in _sql(db.statements[0])


async def test_component_leaderboard_ignores_downloads_from_deleted_agents():
    db = _CaptureDb()

    await component_leaderboard.__wrapped__(window="all", limit=20, user=None, db=db)

    download_queries = [stmt for stmt in db.statements if "agent_download_records" in _sql(stmt)]
    assert len(download_queries) == 5
    assert all("agents.deleted_at IS NULL" in _sql(stmt) for stmt in download_queries)
