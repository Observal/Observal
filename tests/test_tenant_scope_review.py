# SPDX-FileCopyrightText: 2026 Nav-Prak <naveenprakaasam@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tenant-scoping regression coverage for the registry review routes.

These tests assert that review queries are constrained to the caller's
organization (``owner_org_id``) so a reviewer in one org cannot read or act on
listings, agent components, or bundles owned by another org.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from api.routes import review
from api.routes.review import _apply_owner_org_filter, _owner_org_conditions
from models.mcp import ListingStatus, McpListing
from models.user import UserRole


def _scalar_result(obj=None):
    result = MagicMock()
    result.scalar_one.return_value = obj
    result.scalar_one_or_none.return_value = obj
    result.scalars.return_value.all.return_value = [obj] if obj is not None else []
    result.all.return_value = []
    return result


def _where(stmt):
    """WHERE-clause text of a statement.

    A full-entity ``select(Model)`` always lists ``owner_org_id`` in its SELECT
    columns, so the org predicate must be checked against the WHERE clause only.
    """
    return str(stmt.whereclause) if stmt.whereclause is not None else ""


def _reviewer(org_id):
    """A reviewer in org ``org_id`` (or org-less super-admin when None)."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "reviewer@example.com"
    user.role = UserRole.reviewer
    user.org_id = org_id
    return user


class _RecordingSession:
    """Async DB stub that records executed statements and returns queued results.

    Lets route-level tests assert the org predicate reached the query without a
    live database.  Unqueued executes default to an empty result.
    """

    def __init__(self, results=None):
        self.statements = []
        self._results = list(results or [])
        self.committed = False

    async def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        if self._results:
            return self._results.pop(0)
        return _scalar_result(None)

    async def commit(self):
        self.committed = True

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass


def test_review_owner_org_filter_adds_tenant_condition():
    org_id = uuid.uuid4()
    stmt = _apply_owner_org_filter(select(McpListing), McpListing, org_id)

    # No org -> no extra conditions; with an org -> an owner_org_id predicate.
    assert _owner_org_conditions(McpListing, None) == []
    assert "owner_org_id" in str(stmt)


@pytest.mark.asyncio
async def test_find_listing_passes_org_conditions_to_prefix_and_name_lookup():
    from api.routes.review import _find_listing

    org_id = uuid.uuid4()
    listing = MagicMock()
    listing.id = uuid.uuid4()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(listing))
    seen_conditions = []

    async def fake_resolve(*args, **kwargs):
        seen_conditions.append(kwargs.get("extra_conditions"))
        raise HTTPException(status_code=404, detail="not found")

    with patch("api.routes.review.resolve_prefix_id", AsyncMock(side_effect=fake_resolve)):
        listing_type, found = await _find_listing("tenant-mcp", db, org_id)

    assert listing_type == "mcp"
    assert found is listing
    # Org conditions are forwarded to the prefix lookup and the name fallback.
    assert any(seen_conditions)
    assert "owner_org_id" in str(db.execute.call_args[0][0])


@pytest.mark.asyncio
async def test_check_agent_components_ready_blocks_components_outside_org():
    from api.routes.review import _check_agent_components_ready

    comp = MagicMock()
    comp.component_type = "mcp"
    comp.component_id = uuid.uuid4()

    empty_rows = MagicMock()
    empty_rows.all.return_value = []
    db = AsyncMock()
    db.execute = AsyncMock(return_value=empty_rows)

    ready, blocking = await _check_agent_components_ready([comp], db, uuid.uuid4())

    # A component the reviewer's org cannot see blocks approval rather than
    # silently passing.
    assert ready is False
    assert blocking == [
        {
            "component_type": "mcp",
            "component_id": str(comp.component_id),
            "name": "",
            "status": "not_found_or_not_in_org",
        }
    ]
    assert "owner_org_id" in str(db.execute.call_args[0][0])


@pytest.mark.asyncio
async def test_bundle_belongs_to_org_requires_submitter_membership():
    from api.routes.review import _bundle_belongs_to_org

    bundle = MagicMock()
    bundle.submitted_by = uuid.uuid4()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))

    # No org context -> always allowed; with an org -> submitter must be a member.
    assert await _bundle_belongs_to_org(bundle, db, None) is True
    assert await _bundle_belongs_to_org(bundle, db, uuid.uuid4()) is False
    assert "org_id" in str(db.execute.call_args[0][0])


# ---------------------------------------------------------------------------
# Route-level scoping: each handler must constrain reads/writes to the caller's
# org so a reviewer cannot list, read, or act on another org's records.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("tab", [None, "agents", "components"])
async def test_list_pending_threads_caller_org_to_queries(tab):
    org_id = uuid.uuid4()
    agents = AsyncMock(return_value=[])
    components = AsyncMock(return_value=[])
    db = _RecordingSession()

    with (
        patch.object(review, "_query_pending_agents", agents),
        patch.object(review, "_query_pending_components", components),
    ):
        await review.list_pending(type=None, tab=tab, db=db, current_user=_reviewer(org_id))

    # Whichever helper(s) the tab dispatches to must receive the caller's org.
    if tab != "components":
        assert agents.await_args.args[1] == org_id
    if tab != "agents":
        assert components.await_args.args[2] == org_id


@pytest.mark.asyncio
async def test_get_review_denies_cross_org_agent():
    org_id = uuid.uuid4()
    db = _RecordingSession(results=[_scalar_result(None)])  # agent fallback finds nothing

    with (
        patch.object(review, "_find_listing", AsyncMock(return_value=(None, None))) as find,
        pytest.raises(HTTPException) as exc,
    ):
        await review.get_review(listing_id=str(uuid.uuid4()), db=db, current_user=_reviewer(org_id))

    assert exc.value.status_code == 404
    assert find.await_args.args[2] == org_id
    assert any("owner_org_id" in _where(s) for s in db.statements)


@pytest.mark.asyncio
async def test_approve_denies_cross_org_listing():
    org_id = uuid.uuid4()
    db = _RecordingSession()

    with (
        patch.object(review, "_find_listing", AsyncMock(return_value=(None, None))) as find,
        pytest.raises(HTTPException) as exc,
    ):
        await review.approve(listing_id="other-org-mcp", db=db, current_user=_reviewer(org_id))

    assert exc.value.status_code == 404
    assert find.await_args.args[2] == org_id
    assert db.committed is False


@pytest.mark.asyncio
async def test_reject_denies_cross_org_listing():
    org_id = uuid.uuid4()
    db = _RecordingSession()

    with (
        patch.object(review, "_find_listing", AsyncMock(return_value=(None, None))) as find,
        pytest.raises(HTTPException) as exc,
    ):
        await review.reject(
            listing_id="other-org-mcp",
            req=MagicMock(reason="nope"),
            db=db,
            current_user=_reviewer(org_id),
        )

    assert exc.value.status_code == 404
    assert find.await_args.args[2] == org_id
    assert db.committed is False


@pytest.mark.asyncio
async def test_approve_agent_denies_cross_org_agent():
    org_id = uuid.uuid4()
    db = _RecordingSession(results=[_scalar_result(None)])

    with pytest.raises(HTTPException) as exc:
        await review.approve_agent(agent_id=uuid.uuid4(), req=None, db=db, current_user=_reviewer(org_id))

    assert exc.value.status_code == 404
    assert "owner_org_id" in _where(db.statements[0])
    assert db.committed is False


@pytest.mark.asyncio
async def test_approve_agent_query_is_unscoped_for_super_admin():
    # A super-admin has no org and must be able to reach any agent (no filter).
    db = _RecordingSession(results=[_scalar_result(None)])

    with pytest.raises(HTTPException) as exc:
        await review.approve_agent(agent_id=uuid.uuid4(), req=None, db=db, current_user=_reviewer(None))

    assert exc.value.status_code == 404
    assert "owner_org_id" not in _where(db.statements[0])


@pytest.mark.asyncio
async def test_reject_agent_denies_cross_org_agent():
    org_id = uuid.uuid4()
    db = _RecordingSession(results=[_scalar_result(None)])

    with pytest.raises(HTTPException) as exc:
        await review.reject_agent(
            agent_id=uuid.uuid4(),
            req=MagicMock(reason="nope"),
            db=db,
            current_user=_reviewer(org_id),
        )

    assert exc.value.status_code == 404
    assert "owner_org_id" in _where(db.statements[0])
    assert db.committed is False


@pytest.mark.asyncio
async def test_approve_bundle_denies_cross_org_bundle():
    org_id = uuid.uuid4()
    bundle = MagicMock()
    bundle.submitted_by = uuid.uuid4()
    db = _RecordingSession(results=[_scalar_result(bundle)])  # bundle row found...
    belongs = AsyncMock(return_value=False)  # ...but submitter is in another org

    with (
        patch.object(review, "_bundle_belongs_to_org", belongs),
        pytest.raises(HTTPException) as exc,
    ):
        await review.approve_bundle(bundle_id=uuid.uuid4(), db=db, current_user=_reviewer(org_id))

    assert exc.value.status_code == 404
    assert belongs.await_args.args[2] == org_id
    assert db.committed is False


@pytest.mark.asyncio
async def test_reject_bundle_denies_cross_org_bundle():
    org_id = uuid.uuid4()
    bundle = MagicMock()
    bundle.submitted_by = uuid.uuid4()
    db = _RecordingSession(results=[_scalar_result(bundle)])
    belongs = AsyncMock(return_value=False)

    with (
        patch.object(review, "_bundle_belongs_to_org", belongs),
        pytest.raises(HTTPException) as exc,
    ):
        await review.reject_bundle(
            bundle_id=uuid.uuid4(),
            req=MagicMock(reason="nope"),
            db=db,
            current_user=_reviewer(org_id),
        )

    assert exc.value.status_code == 404
    assert belongs.await_args.args[2] == org_id
    assert db.committed is False


@pytest.mark.asyncio
async def test_get_related_skills_returns_empty_for_cross_org_mcp():
    org_id = uuid.uuid4()
    db = _RecordingSession()

    with patch.object(review, "_find_listing", AsyncMock(return_value=(None, None))) as find:
        result = await review.get_related_skills(listing_id="other-org-mcp", db=db, current_user=_reviewer(org_id))

    assert result == {"skills": []}
    assert find.await_args.args[2] == org_id


@pytest.mark.asyncio
async def test_approve_with_skills_denies_cross_org_mcp():
    org_id = uuid.uuid4()
    db = _RecordingSession()

    with (
        patch.object(review, "_find_listing", AsyncMock(return_value=(None, None))) as find,
        pytest.raises(HTTPException) as exc,
    ):
        await review.approve_mcp_with_skills(
            listing_id="other-org-mcp",
            req=review.McpBulkApproveRequest(skill_ids=[]),
            db=db,
            current_user=_reviewer(org_id),
        )

    assert exc.value.status_code == 404
    assert find.await_args.args[2] == org_id
    assert db.committed is False


@pytest.mark.asyncio
async def test_approve_with_skills_scopes_skill_lookup_and_skips_cross_org_skill():
    org_id = uuid.uuid4()
    listing = MagicMock()
    listing.id = uuid.uuid4()
    listing.name = "srv"
    listing.status = ListingStatus.approved
    db = _RecordingSession(results=[_scalar_result(None)])  # the requested skill is in another org

    with patch.object(review, "_find_listing", AsyncMock(return_value=("mcp", listing))):
        result = await review.approve_mcp_with_skills(
            listing_id="srv",
            req=review.McpBulkApproveRequest(skill_ids=[str(uuid.uuid4())]),
            db=db,
            current_user=_reviewer(org_id),
        )

    # The cross-org skill is not found under the org filter, so nothing is approved.
    assert result["approved_skills"] == 0
    assert result["skill_ids"] == []
    assert any("owner_org_id" in _where(s) for s in db.statements)
