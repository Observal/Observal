# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Visible review queue. Always filter before paginating to avoid leaking metadata."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from api.routes.reviews.common import participant
from models.agent_component import AgentComponent
from models.review import Review, ReviewComment, ReviewReviewerRequest, ReviewState, ReviewSubmission, ReviewThread
from models.user import User
from services.review.decisions import _own_work, _target, gate
from services.teamspace import review_scope

router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])


async def summary(db, review, user):
    from api.routes.reviews.common import head

    latest = await head(db, review)
    result = await gate(db, review)
    requested = await db.get(ReviewReviewerRequest, (review.id, user.id))
    mine = await db.scalar(
        select(ReviewSubmission)
        .where(
            ReviewSubmission.review_id == review.id,
            ReviewSubmission.reviewer_id == user.id,
            ReviewSubmission.state == "submitted",
        )
        .order_by(ReviewSubmission.submitted_at.desc(), ReviewSubmission.id.desc())
        .limit(1)
    )
    thread_rows = (
        await db.execute(
            select(ReviewThread.id, ReviewThread.resolved_at, ReviewSubmission.state, ReviewSubmission.reviewer_id)
            .join(ReviewComment, ReviewComment.thread_id == ReviewThread.id)
            .outerjoin(ReviewSubmission, ReviewSubmission.id == ReviewComment.submission_id)
            .where(ReviewThread.review_id == review.id)
        )
    ).all()
    visible_threads = {
        tid: resolved for tid, resolved, state, author in thread_rows if state != "draft" or author == user.id
    }
    checks = {
        status: sum(c.get("status") == status for c in latest.checks) for status in ("pass", "fail", "warn", "skipped")
    }
    dependencies = []
    if review.subject_type == "agent":
        pins = (
            await db.scalars(
                select(AgentComponent.resolved_version_id).where(
                    AgentComponent.agent_version_id == review.version_id,
                    AgentComponent.resolved_version_id.is_not(None),
                )
            )
        ).all()
        if pins:
            linked = (await db.scalars(select(Review).where(Review.version_id.in_(pins)))).all()
            dependencies = [r.number for r in linked if await participant(db, r, user)]
    return {
        "depends_on": dependencies,
        "threads": {
            "total": len(visible_threads),
            "unresolved": sum(resolved is None for resolved in visible_threads.values()),
        },
        "checks": checks,
        "id": review.id,
        "number": review.number,
        "title": review.title,
        "subject_type": review.subject_type,
        "subject_id": review.subject_id,
        "version": review.version,
        "team_id": review.team_id,
        "state": review.state.value,
        "author_id": review.opened_by,
        "head_revision": latest.number,
        "updated_at": review.updated_at,
        "gate": {
            "ready": result.ready,
            "approvals": result.approvals,
            "required": result.required,
            "requirements": result.requirements,
            "policy_source": result.policy_source,
        },
        "requested_from_me": requested is not None,
        "my_last_submission": ({"verdict": mine.verdict, "revision_id": mine.revision_id} if mine else None),
    }


@router.get("")
async def list_reviews(
    state: str = "open",
    type: str | None = None,
    team_id: uuid.UUID | None = None,
    author: str | None = None,
    requested: str | None = None,
    needs: str | None = None,
    q: str | None = None,
    cursor: int | None = None,
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if state not in {"open", "changes_requested", "approved", "published", "closed", "all"}:
        raise HTTPException(422, "Unknown state")
    if type and type not in {"agent", "mcp", "skill", "hook", "prompt", "sandbox"}:
        raise HTTPException(422, "Unknown subject type")
    if (
        author not in (None, "me")
        or requested not in (None, "me")
        or needs not in (None, "my_review", "ready_to_publish")
    ):
        raise HTTPException(422, "Invalid queue filter")
    scope = await review_scope(db, user)
    if scope.is_empty and author != "me":
        raise HTTPException(403, "Review queue requires reviewer scope; use author=me")
    stmt = select(Review)
    if state == "open":
        stmt = stmt.where(Review.state.in_((ReviewState.open, ReviewState.changes_requested, ReviewState.approved)))
    elif state != "all":
        stmt = stmt.where(Review.state == ReviewState(state))
    if type:
        stmt = stmt.where(Review.subject_type == type)
    if team_id:
        stmt = stmt.where(Review.team_id == team_id)
    if requested == "me":
        stmt = stmt.join(ReviewReviewerRequest, ReviewReviewerRequest.review_id == Review.id).where(
            ReviewReviewerRequest.user_id == user.id
        )
    if cursor is not None:
        stmt = stmt.where(Review.number < cursor)
    if q:
        from api.sanitize import escape_like

        stmt = stmt.where(Review.title.ilike(f"%{escape_like(q.strip())}%", escape="\\"))
    # ACL is evaluated on every candidate BEFORE a page is taken. Phase 2 has no
    # active submit path; phase 3 can move this into a SQL visibility predicate.
    reviews = (await db.execute(stmt.order_by(Review.number.desc()))).scalars().all()
    visible = []
    for review in reviews:
        if not await participant(db, review, user, scope=scope):
            continue
        if author == "me":
            subject, version = await _target(db, review)
            if not _own_work(subject, version, user.id):
                continue
        visible.append(review)
    rows = []
    for review in visible:
        item = await summary(db, review, user)
        if needs == "ready_to_publish" and not item["gate"]["ready"]:
            continue
        if needs == "my_review" and (
            item["my_last_submission"] is not None
            and item["my_last_submission"]["revision_id"] == review.head_revision_id
        ):
            continue
        rows.append(item)
        if len(rows) == limit + 1:
            break
    return {"items": rows[:limit], "next_cursor": rows[limit - 1]["number"] if len(rows) > limit else None}
