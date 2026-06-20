# SPDX-FileCopyrightText: 2026 Nav-Prak <naveenprakaasam@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tenant-scoping regression coverage for security events.

Security events are stamped with the actor's organization on emit and the
admin query is constrained to the caller's org, so a tenant admin cannot read
another organization's security events.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from models.user import UserRole


def _admin_user(org_id: uuid.UUID | None = None):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "admin@example.com"
    user.role = UserRole.admin
    user.org_id = org_id
    return user


@pytest.mark.asyncio
async def test_security_events_query_is_org_scoped_for_tenant_admin():
    from api.routes.admin.org import get_security_events

    org_id = uuid.uuid4()
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {"data": [], "rows": 0}
    mock_query = AsyncMock(return_value=fake_resp)

    with patch("services.clickhouse._query", mock_query):
        result = await get_security_events(current_user=_admin_user(org_id))

    assert result == {"events": [], "total": 0}
    sql_arg = mock_query.call_args[0][0]
    params_arg = mock_query.call_args[0][1]
    assert "org_id = {org_id:String}" in sql_arg
    assert params_arg["param_org_id"] == str(org_id)


@pytest.mark.asyncio
async def test_emit_security_event_resolves_org_id_before_clickhouse_insert():
    from services.security_events import EventType, SecurityEvent, Severity, emit_security_event

    event = SecurityEvent(
        event_type=EventType.PERMISSION_DENIED,
        severity=Severity.WARNING,
        outcome="failure",
        actor_id=str(uuid.uuid4()),
    )
    mock_query = AsyncMock()

    with (
        patch("services.security_events._resolve_actor_org_id", AsyncMock(return_value="org-a")),
        patch("services.clickhouse._query", mock_query),
    ):
        await emit_security_event(event)

    assert event.org_id == "org-a"
    inserted = json.loads(mock_query.call_args.kwargs["data"])
    assert inserted["org_id"] == "org-a"


def test_security_events_org_id_has_existing_deployment_migration():
    """org_id must be backfilled via ALTER, not only the CREATE TABLE.

    CREATE TABLE IF NOT EXISTS is a no-op once the table exists, so a
    deployment that created security_events before org_id was added would
    never gain the column and would fail on org-scoped insert/query.
    """
    from services.clickhouse.schema import INIT_SQL

    sql_blob = "\n".join(INIT_SQL)
    assert "ALTER TABLE security_events ADD COLUMN IF NOT EXISTS org_id" in sql_blob
    assert "ALTER TABLE security_events ADD INDEX IF NOT EXISTS idx_org_id" in sql_blob


@pytest.mark.asyncio
async def test_resolve_actor_org_id_reads_database_once_and_caches_result():
    import services.security_events as security_events

    security_events._ACTOR_ORG_CACHE.clear()
    actor_id = str(uuid.uuid4())
    org_id = uuid.uuid4()

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = org_id
    db = AsyncMock()
    db.execute = AsyncMock(return_value=query_result)

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch("database.async_session", MagicMock(return_value=FakeSession())):
        first = await security_events._resolve_actor_org_id(actor_id)
        second = await security_events._resolve_actor_org_id(actor_id)

    assert first == str(org_id)
    assert second == str(org_id)
    db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Login-failure attribution: a wrong-password attempt against a *real* user must
# carry that user's id so emit_security_event can resolve their org -- otherwise
# the org-scoped admin query hides the failure from the user's tenant admins.
# ---------------------------------------------------------------------------


def _failed_login_event(handler_name, *, user, identifier):
    """Drive the auth handler's wrong-password path and return the emitted event.

    Calls the undecorated handler (``__wrapped__``) to bypass the rate limiter.
    """
    from api.routes import auth

    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    req = MagicMock()
    req.email = identifier
    req.password = "wrong-password"

    captured = []
    emit = AsyncMock(side_effect=lambda ev: captured.append(ev))
    raw = getattr(auth, handler_name).__wrapped__

    async def _run():
        with (
            patch("api.routes.auth.emit_security_event", emit),
            pytest.raises(HTTPException) as exc,
        ):
            await raw(request=MagicMock(), req=req, db=db)
        assert exc.value.status_code == 401

    return _run, captured


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", ["login", "issue_token"])
async def test_login_failure_for_existing_user_is_org_attributable(handler_name):
    from services.security_events import EventType

    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "real@tenant.example"
    user.role = UserRole.user
    user.verify_password = MagicMock(return_value=False)

    run, captured = _failed_login_event(handler_name, user=user, identifier=user.email)
    await run()

    assert len(captured) == 1
    event = captured[0]
    assert event.event_type == EventType.LOGIN_FAILURE
    # Attributed to the real user so emit resolves their org (visible to tenant admins).
    assert event.actor_id == str(user.id)
    assert event.actor_email == user.email
    assert event.actor_role == user.role.value


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", ["login", "issue_token"])
async def test_login_failure_for_unknown_user_stays_orgless(handler_name):
    from services.security_events import EventType

    identifier = "ghost@nowhere.example"
    run, captured = _failed_login_event(handler_name, user=None, identifier=identifier)
    await run()

    assert len(captured) == 1
    event = captured[0]
    assert event.event_type == EventType.LOGIN_FAILURE
    # No such user -> no org attribution; the attempt stays global.
    assert event.actor_id == ""
    assert event.actor_email == identifier
