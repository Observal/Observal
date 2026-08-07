# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tenant-scoping regression coverage for audit log reads and writes."""

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
@pytest.mark.parametrize("endpoint", ["list", "export"])
async def test_audit_reads_are_org_scoped(endpoint):
    from api.routes import audit_log

    org_id = uuid.uuid4()
    response = MagicMock(status_code=200, text="")
    query = AsyncMock(return_value=response)
    user = _admin_user(org_id)

    with patch.object(audit_log, "_query", query):
        if endpoint == "list":
            result = await audit_log.list_audit_logs(
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
                db=None,
                current_user=user,
            )
            assert result == []
        else:
            await audit_log.export_audit_logs(
                actor=None,
                action=None,
                resource_type=None,
                sensitivity=None,
                outcome=None,
                source=None,
                start_date=None,
                end_date=None,
                format="json",
                db=None,
                current_user=user,
            )

    sql, params = query.call_args.args
    assert "org_id = {org_id:String}" in sql
    assert params["param_org_id"] == str(org_id)


@pytest.mark.asyncio
async def test_buffer_row_resolves_and_caches_actor_org():
    import services.audit.event_handlers as audit

    audit._actor_org_cache.clear()
    audit._audit_buffer.clear()
    actor_id = str(uuid.uuid4())
    row = audit._make_row(
        actor_id=actor_id,
        actor_email="actor@example.com",
        action="user.created",
        resource_type="user",
    )

    with patch.object(audit, "_resolve_actor_org_id", AsyncMock(return_value="org-9")) as resolver:
        await audit._buffer_row(row)

    assert row["org_id"] == "org-9"
    resolver.assert_awaited_once_with(actor_id)
    audit._audit_buffer.clear()


@pytest.mark.asyncio
async def test_explicit_org_id_skips_actor_lookup():
    import services.audit.event_handlers as audit

    audit._audit_buffer.clear()
    row = audit._make_row(
        actor_id=str(uuid.uuid4()),
        actor_email="deleted@example.com",
        org_id="org-7",
        action="user.deleted",
        resource_type="user",
    )

    with patch.object(audit, "_resolve_actor_org_id", AsyncMock()) as resolver:
        await audit._buffer_row(row)

    assert row["org_id"] == "org-7"
    resolver.assert_not_awaited()
    audit._audit_buffer.clear()
