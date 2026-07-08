# SPDX-FileCopyrightText: 2026 Nav-Prak <naveenprakaasam@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tenant-scoping regression coverage for the enterprise audit log.

Audit rows are stamped with the actor's organization (resolved from the
database and cached per actor) and the audit-log list/export queries are
constrained to the caller's org, so a tenant admin cannot read another
organization's audit trail.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.user import UserRole


def _admin_user(org_id: uuid.UUID | None = None):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "admin@example.com"
    user.role = UserRole.admin
    user.org_id = org_id
    return user


@pytest.mark.asyncio
async def test_audit_log_query_is_org_scoped_for_tenant_admin():
    from ee.observal_server.routes.audit import list_audit_logs

    org_id = uuid.uuid4()
    fake_resp = MagicMock(status_code=200, text="")
    mock_query = AsyncMock(return_value=fake_resp)

    with patch("ee.observal_server.routes.audit._query", mock_query):
        result = await list_audit_logs(
            actor=None,
            action=None,
            resource_type=None,
            sensitivity=None,
            outcome=None,
            source=None,
            start_date=None,
            end_date=None,
            limit=50,
            offset=0,
            current_user=_admin_user(org_id),
        )

    assert result == []
    sql_arg = mock_query.call_args[0][0]
    params_arg = mock_query.call_args[0][1]
    assert "org_id = {org_id:String}" in sql_arg
    assert params_arg["param_org_id"] == str(org_id)


@pytest.mark.asyncio
async def test_export_audit_log_query_is_org_scoped_for_tenant_admin():
    from ee.observal_server.routes.audit import export_audit_logs

    org_id = uuid.uuid4()
    fake_resp = MagicMock(status_code=200, text="")
    mock_query = AsyncMock(return_value=fake_resp)

    with patch("ee.observal_server.routes.audit._query", mock_query):
        await export_audit_logs(
            actor=None,
            action=None,
            resource_type=None,
            sensitivity=None,
            outcome=None,
            source=None,
            start_date=None,
            end_date=None,
            format="json",
            current_user=_admin_user(org_id),
        )

    sql_arg = mock_query.call_args[0][0]
    params_arg = mock_query.call_args[0][1]
    assert "org_id = {org_id:String}" in sql_arg
    assert params_arg["param_org_id"] == str(org_id)


@pytest.mark.asyncio
async def test_buffer_row_resolves_and_stamps_actor_org_id():
    import ee.observal_server.services.audit as audit

    audit._actor_org_cache.clear()
    audit._audit_buffer.clear()

    row = audit._make_row(
        actor_id=str(uuid.uuid4()),
        actor_email="a@example.com",
        action="user.created",
        resource_type="user",
    )
    # _make_row leaves org_id unset; _buffer_row resolves it from the actor.
    assert row["org_id"] == ""

    with patch.object(audit, "_resolve_actor_org_id", AsyncMock(return_value="org-9")):
        await audit._buffer_row(row)

    assert row["org_id"] == "org-9"
    assert audit._audit_buffer[-1] is row
    audit._audit_buffer.clear()


@pytest.mark.asyncio
async def test_resolve_actor_org_id_reads_database_once_and_caches_result():
    import ee.observal_server.services.audit as audit

    audit._actor_org_cache.clear()
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
        first = await audit._resolve_actor_org_id(actor_id)
        second = await audit._resolve_actor_org_id(actor_id)

    assert first == str(org_id)
    assert second == str(org_id)
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_deleted_audit_row_uses_event_org_id_without_db_lookup():
    """A UserDeleted audit row must stay tenant-scoped.

    SCIM emits UserDeleted *after* deleting the user, so resolving org_id from
    the actor row would find nothing and the row would land orgless (hidden from
    tenant admins). The event carries org_id captured before deletion; the
    handler must use it and skip the actor lookup.
    """
    import ee.observal_server.services.audit as audit
    from services.events import UserDeleted, bus

    audit._actor_org_cache.clear()
    audit._audit_buffer.clear()
    bus.clear()
    audit.register_audit_handlers()
    # would return "" for an already-deleted user
    resolver = AsyncMock(return_value="")

    try:
        with (
            patch.object(audit, "_resolve_actor_org_id", resolver),
            patch.object(audit, "_enrich_with_http_context", lambda row: row),
        ):
            await bus.emit(UserDeleted(user_id=str(uuid.uuid4()), email="gone@tenant.example", org_id="org-7"))

        assert audit._audit_buffer, "expected the deletion to buffer an audit row"
        row = audit._audit_buffer[-1]
        assert row["action"] == "user.deleted"
        assert row["org_id"] == "org-7"
        resolver.assert_not_awaited()
    finally:
        if audit._flush_task is not None:
            audit._flush_task.cancel()
            audit._flush_task = None
        audit._audit_buffer.clear()
        bus.clear()
