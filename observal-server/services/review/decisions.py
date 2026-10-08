# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Transactional review rules. Not called by legacy routes until the API/UI cutover."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select, update

from models.agent import Agent, AgentStatus, AgentVersion
from models.agent_component import AgentComponent
from models.mcp import ListingStatus
from models.review import (
    Review,
    ReviewComment,
    ReviewEvent,
    ReviewRevision,
    ReviewState,
    ReviewSubmission,
    ReviewThread,
)
from models.user import UserRole
from services.agent_lock import LISTING_MODELS, VERSION_MODELS, latest_release, lock_agent_version
from services.editing_lock import is_actively_editing
from services.review.anchors import reanchor
from services.review.checks import pinned_component_blockers, snapshot_checks
from services.review.files import render_files
from services.review.policy import ApprovalPolicy, policy_for
from services.teamspace import can_review, review_scope
from services.versioning import parse_semver


def _now():
    return datetime.now(UTC)


def _event(db, review, kind, actor_id=None, *, at=None, **payload):
    db.add(ReviewEvent(review_id=review.id, kind=kind, actor_id=actor_id, created_at=at or _now(), payload=payload))


def _hash(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def _target(db, review):
    if review.subject_type == "agent":
        version = await db.get(AgentVersion, review.version_id)
        subject = await db.get(Agent, review.subject_id)
    else:
        model = VERSION_MODELS[review.subject_type]
        version = await db.get(model, review.version_id)
        subject = await db.get(LISTING_MODELS[review.subject_type], review.subject_id)
    if (
        not version
        or not subject
        or (version.agent_id if review.subject_type == "agent" else version.listing_id) != subject.id
    ):
        raise HTTPException(404, "Review subject no longer exists")
    return subject, version


def _own_work(subject, version, actor_id) -> bool:
    owner_id = getattr(subject, "created_by", None) or getattr(subject, "submitted_by", None)
    return actor_id in (version.released_by, owner_id) or str(actor_id) in (subject.co_authors or [])


async def _require_reviewer(db, review, user):
    subject, _ = await _target(db, review)
    if not can_review(subject, await review_scope(db, user)):
        raise HTTPException(403, "Not a reviewer in scope")


async def _lock_review(db, review):
    await db.execute(select(Review.id).where(Review.id == review.id).with_for_update())


async def _head(db, review):
    head = await db.get(ReviewRevision, review.head_revision_id)
    if head is None:
        raise HTTPException(409, "Review has no head revision")
    return head


async def _base_files(db, subject_type, version, base_version_id) -> dict:
    """Render the frozen review base; checks compare against it, never the previous revision."""
    if base_version_id is None:
        return {}
    base = await db.get(type(version), base_version_id)
    return await render_files(subject_type, base, db) if base is not None else {}


async def open_or_push(
    db,
    subject_type: str,
    subject,
    version,
    actor_id,
    *,
    message=None,
    backfill=False,
    policy=None,
    visibility_requeue=False,
):
    """Create a review or push a revision in the caller's transaction."""
    if subject_type not in (*VERSION_MODELS, "agent"):
        raise ValueError("Unsupported review subject")
    review = (
        await db.execute(
            select(Review).where(Review.subject_type == subject_type, Review.version_id == version.id).with_for_update()
        )
    ).scalar_one_or_none()
    if review and backfill:
        return review  # Never rewrite an active review from a stale legacy version.
    if review and review.state == ReviewState.published and not visibility_requeue:
        raise HTTPException(409, "Published versions require a new version and review")
    if visibility_requeue and review and review.state != ReviewState.published:
        raise HTTPException(409, "Only published reviews can be requeued for public visibility")
    files = await render_files(subject_type, version, db)
    digest = _hash(files)
    if review:
        if review.state == ReviewState.closed and review.closed_reason == "superseded":
            raise HTTPException(409, "Superseded reviews cannot be reopened; release a new version")
        head = await _head(db, review)
        base_files = await _base_files(db, subject_type, version, review.base_version_id)
        if head.content_hash == digest and not visibility_requeue:
            raise HTTPException(409, "No content changes since the previous revision")
        if visibility_requeue:
            # Team-private approvals must not count toward a public decision,
            # including when policy permits approvals from earlier revisions.
            await db.execute(
                update(ReviewSubmission)
                .where(ReviewSubmission.review_id == review.id, ReviewSubmission.state == "submitted")
                .values(
                    state="dismissed",
                    dismissed_by=actor_id,
                    dismissed_at=_now(),
                    dismissed_reason="Visibility changed to public",
                )
            )
            review.published_at = None
            review.published_by = None
            review.is_private = subject.is_private
            review.team_id = subject.team_id
            _event(db, review, "visibility_requeued", actor_id)
        next_number = head.number + 1
        threads = (await db.execute(select(ReviewThread).where(ReviewThread.review_id == review.id))).scalars().all()
        moved, outdated = reanchor(threads, head.files, files)
        was_closed = review.state == ReviewState.closed
        review.state = ReviewState.open
        review.closed_reason = None
        review.closed_at = None
        review.closed_by = None
        _event(
            db,
            review,
            "reopened" if was_closed else "revision_pushed",
            actor_id,
            revision=next_number,
            moved=moved,
            outdated=outdated,
        )
    else:
        latest = await db.get(type(version), subject.latest_version_id) if subject.latest_version_id else None
        if latest is None or latest.status not in (
            ListingStatus.approved,
            AgentStatus.approved,
            ListingStatus.archived,
        ):
            siblings = (
                (
                    await db.execute(
                        select(type(version)).where(
                            (AgentVersion.agent_id if subject_type == "agent" else type(version).listing_id)
                            == subject.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            latest = latest_release(siblings)
        base_files = await _base_files(db, subject_type, version, latest.id if latest else None)
        review = Review(
            subject_type=subject_type,
            subject_id=subject.id,
            version_id=version.id,
            version=version.version,
            base_version_id=latest.id if latest else None,
            state=ReviewState.open,
            title=f"{subject.name} v{version.version}",
            body=getattr(version, "changelog", None) or "",
            opened_by=actor_id if backfill or visibility_requeue else version.released_by,
            opened_at=version.released_at if backfill else _now(),
            team_id=subject.team_id,
            is_private=subject.is_private,
        )
        if db.bind.dialect.name == "sqlite":
            # SQLite test databases have no sequences; PostgreSQL always uses review_number_seq.
            review.number = (await db.scalar(select(func.coalesce(func.max(Review.number), 0)))) + 1
        db.add(review)
        await db.flush()
        next_number = 1
        _event(db, review, "opened", actor_id, at=review.opened_at, revision=1)
    revision = ReviewRevision(
        review_id=review.id,
        number=next_number,
        files=files,
        content_hash=digest,
        checks=snapshot_checks(files, version, subject_type=subject_type, base_files=base_files),
        message=message,
        created_by=actor_id,
    )
    db.add(revision)
    await db.flush()
    review.head_revision_id = revision.id
    # Historical backfill never changes version status.
    if not backfill:
        version.status = AgentStatus.pending if subject_type == "agent" else ListingStatus.pending
        if next_number > 1:
            # Approvals that still count under the policy can make the new head publishable.
            await sync_state(db, review, actor_id=actor_id, policy=policy)
    return review


@dataclass(frozen=True)
class Gate:
    ready: bool
    approvals: int
    required: int
    policy_source: str
    requirements: tuple[str, ...]
    outstanding_requests: int


async def gate(db, review, *, policy: ApprovalPolicy | None = None) -> Gate:
    policy = policy or await policy_for(review, db=db)
    head = await _head(db, review)
    submissions = (
        (
            await db.execute(
                select(ReviewSubmission)
                .where(ReviewSubmission.review_id == review.id, ReviewSubmission.state == "submitted")
                .order_by(ReviewSubmission.submitted_at, ReviewSubmission.id)
            )
        )
        .scalars()
        .all()
    )
    # A reviewer may submit several verdicts. The last relevant verdict wins;
    # old approvals only count if policy explicitly permits them.
    latest = {}
    for submission in submissions:
        if (submission.revision_id == head.id or not policy.dismiss_stale_approvals) and submission.verdict in (
            "approve",
            "request_changes",
        ):
            latest[submission.reviewer_id] = submission
    approvals = sum(
        s.verdict == "approve" and (not s.self_review or policy.self_approval == "counted") for s in latest.values()
    )
    revisions = {
        r.id: r.number
        for r in (await db.execute(select(ReviewRevision).where(ReviewRevision.review_id == review.id))).scalars().all()
    }
    # Submissions are chronological. A change request stays outstanding until the
    # same reviewer later approves that revision or a newer one.
    requests = {}
    for s in submissions:
        if s.verdict == "request_changes":
            requests[s.reviewer_id] = s
        elif (
            s.verdict == "approve"
            and s.reviewer_id in requests
            and revisions[s.revision_id] >= revisions[requests[s.reviewer_id].revision_id]
        ):
            del requests[s.reviewer_id]
    blockers = []
    if approvals < policy.required_approvals[review.subject_type]:
        blockers.append("required_approvals")
    if requests:
        blockers.append("changes_requested")
    if any(check.get("required") and check.get("status") != "pass" for check in head.checks):
        blockers.append("required_checks")
    _, version = await _target(db, review)
    # Saving a draft does not create a revision. Never approve/publish mutable
    # version content that differs from the frozen head reviewers inspected.
    if _hash(await render_files(review.subject_type, version, db)) != head.content_hash:
        blockers.append("unsubmitted_changes")
    if is_actively_editing(version):
        blockers.append("edit_lock")
    # Validation runs after submission, so this is evaluated live rather than snapshotted.
    if review.subject_type == "mcp" and not version.mcp_validated:
        blockers.append("mcp_validation")
    if review.subject_type == "agent" and await pinned_component_blockers(db, review.version_id):
        blockers.append("pinned_components")
    if policy.require_resolved_threads:
        threads = (
            (
                await db.execute(
                    select(ReviewThread)
                    .join(ReviewComment, ReviewComment.thread_id == ReviewThread.id)
                    .outerjoin(ReviewSubmission, ReviewSubmission.id == ReviewComment.submission_id)
                    .where(
                        ReviewThread.review_id == review.id,
                        ReviewThread.resolved_at.is_(None),
                        ReviewThread.outdated.is_(False),
                        (ReviewComment.submission_id.is_(None) | (ReviewSubmission.state != "draft")),
                    )
                    .limit(1)
                )
            )
            .scalars()
            .all()
        )
        if threads:
            blockers.append("unresolved_threads")
    return Gate(
        not blockers,
        approvals,
        policy.required_approvals[review.subject_type],
        policy.source,
        tuple(blockers),
        len(requests),
    )


async def sync_state(db, review, *, actor_id=None, policy=None):
    if review.state in (ReviewState.closed, ReviewState.published):
        return None
    result = await gate(db, review, policy=policy)
    if result.ready and review.state != ReviewState.approved:
        review.state = ReviewState.approved
        _, version = await _target(db, review)
        version.status = AgentStatus.pending if review.subject_type == "agent" else ListingStatus.pending
        _event(db, review, "gate_ready", actor_id)
        if (policy or await policy_for(review, db=db)).auto_publish:
            await publish(db, review, None, auto=True, policy=policy)
    elif (
        result.ready
        and review.state == ReviewState.approved
        and (policy or await policy_for(review, db=db)).auto_publish
    ):
        await publish(db, review, None, auto=True, policy=policy)
    elif not result.ready and review.state == ReviewState.approved:
        review.state = ReviewState.changes_requested if result.outstanding_requests else ReviewState.open
        _, version = await _target(db, review)
        version.status = (
            (AgentStatus.changes_requested if review.subject_type == "agent" else ListingStatus.changes_requested)
            if result.outstanding_requests
            else (AgentStatus.pending if review.subject_type == "agent" else ListingStatus.pending)
        )
        _event(db, review, "gate_lost", actor_id, requirements=result.requirements)
    elif not result.outstanding_requests and review.state == ReviewState.changes_requested:
        review.state = ReviewState.open
        _, version = await _target(db, review)
        version.status = AgentStatus.pending if review.subject_type == "agent" else ListingStatus.pending
    return result


async def submit_verdict(db, review, user, verdict, body="", *, policy=None):
    if verdict not in ("approve", "request_changes", "comment"):
        raise HTTPException(422, "Invalid verdict")
    await _lock_review(db, review)
    subject, version = await _target(db, review)
    if verdict == "comment":
        if not (can_review(subject, await review_scope(db, user)) or _own_work(subject, version, user.id)):
            raise HTTPException(403, "Only participants may comment")
    else:
        await _require_reviewer(db, review, user)
    if review.state in (ReviewState.closed, ReviewState.published):
        raise HTTPException(409, "Review is closed")
    if verdict != "comment" and is_actively_editing(version):
        raise HTTPException(409, "Version is being edited")
    own = _own_work(subject, version, user.id)
    if own and verdict == "request_changes":
        raise HTTPException(403, "Cannot request changes on your own work")
    # Submitting a pending review publishes all of that user's draft comments
    # atomically with their verdict, rather than stranding them in a draft row.
    submission = await db.scalar(
        select(ReviewSubmission)
        .where(
            ReviewSubmission.review_id == review.id,
            ReviewSubmission.reviewer_id == user.id,
            ReviewSubmission.state == "draft",
        )
        .with_for_update()
    )
    if submission is None:
        submission = ReviewSubmission(review_id=review.id, reviewer_id=user.id)
        db.add(submission)
    submission.state = "submitted"
    submission.verdict = verdict
    submission.body = body
    submission.revision_id = review.head_revision_id
    submission.self_review = own
    submission.submitted_at = _now()
    if verdict == "request_changes":
        review.state = ReviewState.changes_requested
        version.status = (
            AgentStatus.changes_requested if review.subject_type == "agent" else ListingStatus.changes_requested
        )
    _event(db, review, "submission", user.id, verdict=verdict)
    await db.flush()
    await sync_state(db, review, actor_id=user.id, policy=policy)
    return submission


async def dismiss(db, review, submission, user, reason, *, policy=None):
    await _lock_review(db, review)
    if review.state in (ReviewState.closed, ReviewState.published):
        raise HTTPException(409, "Review is closed")
    if not reason.strip():
        raise HTTPException(422, "A dismissal reason is required")
    if user.role not in (UserRole.admin, UserRole.super_admin):
        from models.team import TeamMembership, TeamRole

        subject, _ = await _target(db, review)
        row = await db.scalar(
            select(TeamMembership).where(
                TeamMembership.team_id == subject.team_id,
                TeamMembership.user_id == user.id,
                TeamMembership.role == TeamRole.owner,
            )
        )
        if row is None:
            raise HTTPException(403, "Only admins and team owners may dismiss reviews")
    if submission.review_id != review.id or submission.state != "submitted":
        raise HTTPException(409, "Submission is not active")
    submission.state = "dismissed"
    submission.dismissed_by = user.id
    submission.dismissed_at = _now()
    submission.dismissed_reason = reason
    _event(db, review, "approval_dismissed", user.id, submission_id=str(submission.id), reason=reason)
    return await sync_state(db, review, actor_id=user.id, policy=policy)


async def publish(db, review, user, *, category=None, override_reason=None, auto=False, policy=None):
    """No commit: caller must commit status, promotion, lock and review atomically."""
    await _lock_review(db, review)
    if review.state in (ReviewState.closed, ReviewState.published):
        raise HTTPException(409, "Review is closed")
    subject, version = await _target(db, review)
    policy = policy or await policy_for(review, db=db)
    if not auto:
        if user is None:
            raise HTTPException(403, "Publisher required")
        await _require_reviewer(db, review, user)
        if (
            _own_work(subject, version, user.id)
            and not (subject.is_private and policy.source == "teamspace" and policy.self_approval == "counted")
            and not (user.role == UserRole.super_admin and override_reason)
        ):
            raise HTTPException(403, "Authors and co-authors cannot publish their own work")
    if is_actively_editing(version):
        raise HTTPException(409, "Version is being edited")
    if review.subject_type == "agent" and await pinned_component_blockers(db, version.id):
        raise HTTPException(422, "Pinned components must be published first")
    result = await gate(db, review, policy=policy)
    # An administrative policy override cannot approve bytes that have never
    # been submitted as a revision; this is a snapshot-integrity invariant.
    if "unsubmitted_changes" in result.requirements:
        raise HTTPException(409, "Review gate blocked: unsubmitted_changes")
    if not result.ready and not (
        user and user.role == UserRole.super_admin and override_reason and override_reason.strip()
    ):
        raise HTTPException(409, f"Review gate blocked: {', '.join(result.requirements)}")
    if override_reason and (auto or user.role != UserRole.super_admin or not override_reason.strip()):
        raise HTTPException(403, "Only a super admin may override with a reason")
    version.status = AgentStatus.approved if review.subject_type == "agent" else ListingStatus.approved
    version.rejection_reason = None
    version.reviewed_at = _now()
    # A counted approver is the reviewer of record; an override can have none.
    approvals = (
        (
            await db.execute(
                select(ReviewSubmission)
                .where(
                    ReviewSubmission.review_id == review.id,
                    ReviewSubmission.revision_id == review.head_revision_id,
                    ReviewSubmission.verdict == "approve",
                    ReviewSubmission.state == "submitted",
                )
                .order_by(ReviewSubmission.submitted_at.desc())
            )
        )
        .scalars()
        .all()
    )
    version.reviewed_by = next(
        (s.reviewer_id for s in approvals if not s.self_review or policy.self_approval == "counted"), None
    )
    await db.flush()
    if review.subject_type == "agent":
        await lock_agent_version(db, subject, version)
        if category:
            subject.category = category
    current = await db.get(type(version), subject.latest_version_id) if subject.latest_version_id else None
    new_key, old_key = parse_semver(version.version), parse_semver(current.version) if current else None
    if current is None or (new_key is not None and (old_key is None or new_key >= old_key)):
        await db.execute(
            update(type(subject)).where(type(subject).id == subject.id).values(latest_version_id=version.id)
        )
        # Avoid a stale identity-map relationship when the request reuses subject.
        db.expire(subject, ["latest_version_id", "latest_version"])
    review.state = ReviewState.published
    review.published_at = _now()
    review.published_by = user.id if user else None
    review.publish_override_reason = override_reason
    _event(
        db,
        review,
        "publish_override" if override_reason else "auto_published" if auto else "published",
        user.id if user else None,
        reason=override_reason,
    )
    # A newer published release supersedes older still-pending reviews of this subject.
    pending = (
        (
            await db.execute(
                select(Review).where(
                    Review.subject_type == review.subject_type,
                    Review.subject_id == subject.id,
                    Review.id != review.id,
                    Review.state.in_((ReviewState.open, ReviewState.changes_requested, ReviewState.approved)),
                )
            )
        )
        .scalars()
        .all()
    )
    for older in pending:
        older_version = await db.get(type(version), older.version_id)
        if older_version and parse_semver(older.version) and new_key and parse_semver(older.version) < new_key:
            older.state = ReviewState.closed
            older.closed_reason = "superseded"
            older.closed_at = _now()
            older_version.status = AgentStatus.rejected if review.subject_type == "agent" else ListingStatus.rejected
            older_version.rejection_reason = f"Superseded by v{version.version}"
            _event(db, older, "superseded", user.id if user else None, by=review.number)
    if review.subject_type != "agent":
        dependent_ids = (
            (
                await db.execute(
                    select(AgentComponent.agent_version_id).where(
                        AgentComponent.component_type == review.subject_type,
                        AgentComponent.resolved_version_id == version.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for dependent in (
            (
                await db.execute(
                    select(Review).where(
                        Review.subject_type == "agent",
                        Review.version_id.in_(dependent_ids),
                        Review.state.in_((ReviewState.open, ReviewState.changes_requested, ReviewState.approved)),
                    )
                )
            )
            .scalars()
            .all()
        ):
            await sync_state(db, dependent, actor_id=user.id if user else None)
    return review


async def close(db, review, user, reason):
    await _lock_review(db, review)
    await _require_reviewer(db, review, user)
    subject, version = await _target(db, review)
    if _own_work(subject, version, user.id):
        raise HTTPException(403, "Cannot close your own review")
    if not reason.strip() or review.state in (ReviewState.closed, ReviewState.published):
        raise HTTPException(409, "Review is closed or no reason was given")
    if is_actively_editing(version):
        raise HTTPException(409, "Version is being edited")
    review.state = ReviewState.closed
    review.closed_reason = "rejected"
    review.closed_at = _now()
    review.closed_by = user.id
    version.status = AgentStatus.rejected if review.subject_type == "agent" else ListingStatus.rejected
    version.rejection_reason = reason
    _event(db, review, "closed", user.id, reason=reason)
    if review.subject_type != "agent":
        from services.insights.self_learn import handle_component_rejection

        await handle_component_rejection(review.subject_type, subject.id, db)
    return review


async def withdraw(db, review, user):
    await _lock_review(db, review)
    subject, version = await _target(db, review)
    if user.id not in (
        version.released_by,
        getattr(subject, "created_by", None),
        getattr(subject, "submitted_by", None),
    ):
        raise HTTPException(403, "Not the author or owner")
    if review.state in (ReviewState.closed, ReviewState.published):
        raise HTTPException(409, "Review is closed")
    review.state = ReviewState.closed
    review.closed_reason = "withdrawn"
    review.closed_at = _now()
    review.closed_by = user.id
    version.status = AgentStatus.draft if review.subject_type == "agent" else ListingStatus.draft
    _event(db, review, "withdrawn", user.id)
    return review
