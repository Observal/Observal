# SPDX-License-Identifier: Apache-2.0
"""Gate/state transitions on real SQLite rows; no external services."""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from jobs import review_backfill
from models import Base, ReviewRevision, ReviewState, ReviewSubmission
from models.agent import Agent, AgentVersion
from models.agent_component import AgentComponent
from models.mcp import ListingStatus
from models.skill import SkillListing, SkillVersion
from models.team import Team, TeamMembership, TeamRole
from models.user import User, UserRole
from services.review.decisions import dismiss, gate, open_or_push, publish, submit_verdict, sync_state
from services.review.policy import ApprovalPolicy, parse_policy, policy_for


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def fixture_review(db):
    author = User(id=uuid.uuid4(), username="author", email="a@x.test", name="Author", role=UserRole.user)
    reviewer = User(id=uuid.uuid4(), username="reviewer", email="r@x.test", name="Reviewer", role=UserRole.reviewer)
    admin = User(id=uuid.uuid4(), username="admin", email="s@x.test", name="Admin", role=UserRole.super_admin)
    listing = SkillListing(
        name="test skill",
        namespace="tests",
        slug="test-skill",
        owner="author",
        submitted_by=author.id,
        co_authors=[str(admin.id)],
    )
    ver = SkillVersion(
        listing_id=listing.id,
        version="1.0.0",
        description="hello",
        released_by=author.id,
        released_at=datetime.now(UTC),
        task_type="other",
        skill_md_content="# Hello\n",
        status=ListingStatus.pending,
    )
    db.add_all([author, reviewer, admin, listing])
    await db.flush()
    ver.listing_id = listing.id
    db.add(ver)
    await db.flush()
    review = await open_or_push(db, "skill", listing, ver, author.id)
    await db.flush()
    return author, reviewer, admin, listing, ver, review


@pytest.mark.asyncio
async def test_version_rounds_gate_publish_and_author_denial(db):
    author, reviewer, admin, listing, ver, review = await fixture_review(db)
    policy = ApprovalPolicy()
    assert review.number == 1 and review.base_version_id is None
    assert (await gate(db, review, policy=policy)).requirements == ("required_approvals",)
    with pytest.raises(HTTPException) as error:
        await publish(db, review, author, policy=policy)
    assert error.value.status_code == 403
    request = await submit_verdict(db, review, reviewer, "request_changes", policy=policy)
    assert review.state == ReviewState.changes_requested
    assert ver.status == ListingStatus.changes_requested
    ver.skill_md_content = "# Fixed\n"
    await open_or_push(db, "skill", listing, ver, author.id, message="fixed")
    assert review.state == ReviewState.open
    assert (await gate(db, review, policy=policy)).outstanding_requests == 1
    await submit_verdict(db, review, reviewer, "approve", policy=policy)
    assert review.state == ReviewState.approved and ver.status == ListingStatus.pending
    assert (await gate(db, review, policy=policy)).ready
    await publish(db, review, reviewer, policy=policy)
    assert review.state == ReviewState.published and ver.status == ListingStatus.approved
    assert (await db.scalar(select(SkillListing.latest_version_id).where(SkillListing.id == listing.id))) == ver.id
    assert request.state == "submitted"
    assert (
        len((await db.execute(select(ReviewRevision).where(ReviewRevision.review_id == review.id))).scalars().all())
        == 2
    )


@pytest.mark.asyncio
async def test_self_approval_not_counted_override_audited_and_stale(db):
    author, reviewer, admin, listing, ver, review = await fixture_review(db)
    # super-admin is a co-author; self-approval is recorded but doesn't count.
    await submit_verdict(db, review, admin, "approve", policy=ApprovalPolicy())
    assert (await gate(db, review, policy=ApprovalPolicy())).approvals == 0
    with pytest.raises(HTTPException):
        await publish(db, review, admin, policy=ApprovalPolicy())
    await publish(db, review, admin, override_reason="Emergency hotfix", policy=ApprovalPolicy())
    assert review.publish_override_reason == "Emergency hotfix"
    with pytest.raises(HTTPException):
        await open_or_push(db, "skill", listing, ver, author.id)


@pytest.mark.asyncio
async def test_dismiss_change_request_and_stale_approval(db):
    author, reviewer, admin, listing, ver, review = await fixture_review(db)
    approval = await submit_verdict(db, review, reviewer, "approve", policy=ApprovalPolicy())
    assert review.state == ReviewState.approved
    ver.skill_md_content = "# V2\n"
    await open_or_push(db, "skill", listing, ver, author.id)
    assert not (await gate(db, review, policy=ApprovalPolicy())).ready
    assert (await gate(db, review, policy=ApprovalPolicy(dismiss_stale_approvals=False))).approvals == 1
    await dismiss(db, review, approval, admin, "new revision", policy=ApprovalPolicy())
    assert (await gate(db, review, policy=ApprovalPolicy())).approvals == 0
    assert (
        await db.execute(select(ReviewSubmission).where(ReviewSubmission.review_id == review.id))
    ).scalars().first().state == "dismissed"


@pytest.mark.asyncio
async def test_private_team_can_count_own_approval(db):
    author, reviewer, admin, listing, version, review = await fixture_review(db)
    team = Team(name="Example", handle="example", is_private=True, created_by=author.id)
    db.add(team)
    await db.flush()
    db.add(TeamMembership(team_id=team.id, user_id=author.id, role=TeamRole.owner))
    listing.team_id = team.id
    listing.is_private = True
    review.team_id = team.id
    review.is_private = True
    await db.flush()
    policy = ApprovalPolicy(self_approval="counted", source="teamspace")
    await submit_verdict(db, review, author, "approve", policy=policy)
    assert (await gate(db, review, policy=policy)).approvals == 1
    await publish(db, review, author, policy=policy)
    assert review.published_by == author.id


@pytest.mark.asyncio
async def test_agent_waits_for_pinned_release_and_lock(db):
    author, reviewer, admin, listing, component, component_review = await fixture_review(db)
    agent = Agent(name="Agent", namespace="tests", slug="test-agent", owner="author", created_by=author.id)
    db.add(agent)
    await db.flush()
    ver = AgentVersion(
        agent_id=agent.id,
        version="1.0.0",
        description="Agent",
        prompt="Hello",
        model_name="model",
        released_by=author.id,
        released_at=datetime.now(UTC),
    )
    db.add(ver)
    await db.flush()
    db.add(
        AgentComponent(
            agent_version_id=ver.id,
            component_type="skill",
            component_id=listing.id,
            component_name=listing.name,
            resolved_version="1.0.0",
            resolved_version_id=component.id,
        )
    )
    await db.flush()
    review = await open_or_push(db, "agent", agent, ver, author.id)
    await submit_verdict(db, review, reviewer, "approve", policy=ApprovalPolicy())
    assert "pinned_components" in (await gate(db, review, policy=ApprovalPolicy())).requirements
    with pytest.raises(HTTPException) as error:
        await publish(db, review, reviewer, policy=ApprovalPolicy())
    assert error.value.status_code == 422
    await submit_verdict(db, component_review, reviewer, "approve", policy=ApprovalPolicy())
    await publish(db, component_review, reviewer, policy=ApprovalPolicy())
    await sync_state(db, review, policy=ApprovalPolicy())
    assert review.state == ReviewState.approved


@pytest.mark.asyncio
async def test_auto_publish_and_edit_lock(db):
    author, reviewer, admin, listing, version, review = await fixture_review(db)
    policy = ApprovalPolicy(auto_publish=True)
    version.is_editing = True
    version.editing_by = author.id
    version.editing_since = datetime.now(UTC)
    with pytest.raises(HTTPException):
        await submit_verdict(db, review, reviewer, "approve", policy=policy)
    version.is_editing = False
    await submit_verdict(db, review, reviewer, "approve", policy=policy)
    assert review.state == ReviewState.published and review.published_by is None


def test_policy_input_rejects_bool_counts_and_invalid_values():
    with pytest.raises(ValueError):
        parse_policy({"required_approvals": {"skill": True}})
    assert parse_policy({"required_approvals": {"agent": 2}}).required_approvals["agent"] == 2


@pytest.mark.asyncio
async def test_policy_team_public_cannot_lower_org(monkeypatch):
    org = '{"required_approvals":{"skill":2},"auto_publish":true}'
    team = '{"required_approvals":{"skill":1},"self_approval":"counted"}'

    async def get(key, default=""):
        return org if key == "review.policy" else team

    monkeypatch.setattr("services.review.policy.ds.get", get)
    private = type("Subject", (), {"team_id": uuid.uuid4(), "is_private": True})()
    public = type("Subject", (), {"team_id": private.team_id, "is_private": False})()
    assert (await policy_for(private)).required_approvals["skill"] == 1
    result = await policy_for(public)
    assert result.required_approvals["skill"] == 2 and result.self_approval == "not_counted"
    assert not result.auto_publish


@pytest.mark.asyncio
async def test_backfill_idempotent_and_does_not_change_legacy_status(db, monkeypatch):
    author, reviewer, admin, listing, ver, _ = await fixture_review(db)
    await db.commit()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    monkeypatch.setattr(review_backfill, "async_session", factory)
    newer = SkillVersion(
        listing_id=listing.id,
        version="1.1.0",
        description="next",
        released_by=author.id,
        released_at=datetime.now(UTC),
        task_type="other",
        skill_md_content="# New\n",
        status=ListingStatus.pending,
    )
    db.add(newer)
    await db.commit()
    assert await review_backfill.backfill_pending(batch_size=1) == 1
    assert await review_backfill.backfill_pending(batch_size=1) == 0
    assert (await db.scalar(select(ReviewRevision).where(ReviewRevision.review_id != _.id))).number == 1
    assert ver.status == ListingStatus.pending
