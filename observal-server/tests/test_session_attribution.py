# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import uuid

import pytest

from services.session_ingest import _resolve_agent_version


@pytest.mark.asyncio
async def test_resolve_agent_version_keeps_pinned_version(monkeypatch):
    def fail_get_redis():
        raise AssertionError("redis should not be used")

    monkeypatch.setattr("services.redis.get_redis", fail_get_redis)

    result = await _resolve_agent_version(str(uuid.uuid4()), "1.0.0")

    assert result == "1.0.0"


@pytest.mark.asyncio
async def test_resolve_agent_version_latest_alias(monkeypatch):
    class FakeResult:
        def scalar_one_or_none(self):
            return "1.0.0"

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            return FakeResult()

    def fail_get_redis():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("services.redis.get_redis", fail_get_redis)
    monkeypatch.setattr("database.async_session", lambda: FakeSession())

    result = await _resolve_agent_version(str(uuid.uuid4()), "latest")

    assert result == "1.0.0"
