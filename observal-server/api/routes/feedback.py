# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger as optic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role
from models.agent import Agent
from models.feedback import Feedback
from models.hook import HookListing
from models.mcp import McpListing
from models.prompt import PromptListing
from models.sandbox import SandboxListing
from models.skill import SkillListing
from models.user import User, UserRole
from schemas.feedback import FeedbackCreateRequest, FeedbackResponse, FeedbackSummary, FeedbackUpdateRequest
from services.clickhouse import insert_scores

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])

LISTING_MODELS = {
    "mcp": McpListing,
    "agent": Agent,
    "skill": SkillListing,
    "hook": HookListing,
    "prompt": PromptListing,
    "sandbox": SandboxListing,
}


def _serialize_feedback(fb: Feedback) -> FeedbackResponse:
    """Serialize feedback, redacting user_id when anonymous."""
    return FeedbackResponse(
        id=fb.id,
        listing_id=fb.listing_id,
        listing_type=fb.listing_type,
        user_id=None if fb.anonymous else fb.user_id,
        rating=fb.rating,
        comment=fb.comment,
        anonymous=fb.anonymous,
        created_at=fb.created_at,
        updated_at=fb.updated_at,
    )


@router.post("", response_model=FeedbackResponse, status_code=201)
async def create_feedback(
    req: FeedbackCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Submit a review. One review per user per listing (returns 409 if already reviewed)."""
    optic.debug("feedback create: user={}, listing={}", current_user.id, req.listing_id)

    # Validate listing exists
    model = LISTING_MODELS.get(req.listing_type)
    if not model:
        raise HTTPException(status_code=400, detail=f"Unknown listing type: {req.listing_type}")
    exists = await db.scalar(select(model.id).where(model.id == req.listing_id))
    if not exists:
        raise HTTPException(status_code=404, detail="Listing not found")

    # Enforce one review per user per listing
    existing = await db.scalar(
        select(Feedback.id).where(
            Feedback.user_id == current_user.id,
            Feedback.listing_id == req.listing_id,
            Feedback.listing_type == req.listing_type,
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="You have already reviewed this item. Use PUT to update your review.",
        )

    fb = Feedback(
        listing_id=req.listing_id,
        listing_type=req.listing_type,
        user_id=current_user.id,
        rating=req.rating,
        comment=req.comment,
        anonymous=req.anonymous,
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)

    # Dual-write to ClickHouse scores table
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    try:
        await insert_scores(
            [
                {
                    "score_id": str(fb.id),
                    "project_id": "default",
                    "mcp_id": str(req.listing_id) if req.listing_type == "mcp" else None,
                    "agent_id": str(req.listing_id) if req.listing_type == "agent" else None,
                    "user_id": str(current_user.id),
                    "name": "user_rating",
                    "source": "api",
                    "data_type": "numeric",
                    "value": float(req.rating),
                    "comment": req.comment,
                    "metadata": {"listing_type": req.listing_type, "anonymous": req.anonymous},
                    "timestamp": now,
                }
            ]
        )
    except Exception:
        optic.warning("ClickHouse dual-write failed for feedback id={}", fb.id)

    return _serialize_feedback(fb)


@router.get("/mine/{listing_type}/{listing_id}", response_model=FeedbackResponse)
async def get_my_review(
    listing_type: str,
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Get the current user's review for a specific listing (if it exists)."""
    if listing_type not in LISTING_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown listing type: {listing_type}")
    result = await db.execute(
        select(Feedback).where(
            Feedback.user_id == current_user.id,
            Feedback.listing_id == listing_id,
            Feedback.listing_type == listing_type,
        )
    )
    fb = result.scalar_one_or_none()
    if not fb:
        raise HTTPException(status_code=404, detail="You have not reviewed this item")
    return _serialize_feedback(fb)


@router.put("/{feedback_id}", response_model=FeedbackResponse)
async def update_feedback(
    feedback_id: uuid.UUID,
    req: FeedbackUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Update the current user's review. Only the review owner can update."""
    result = await db.execute(select(Feedback).where(Feedback.id == feedback_id))
    fb = result.scalar_one_or_none()
    if not fb:
        raise HTTPException(status_code=404, detail="Review not found")
    if fb.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only update your own review")

    if req.rating is not None:
        fb.rating = req.rating
    if req.comment is not None:
        fb.comment = req.comment
    if req.anonymous is not None:
        fb.anonymous = req.anonymous
    fb.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(fb)
    optic.debug("feedback updated: id={}", feedback_id)
    return _serialize_feedback(fb)


@router.delete("/{feedback_id}", status_code=204)
async def delete_feedback(
    feedback_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Delete the current user's review. Only the review owner can delete."""
    result = await db.execute(select(Feedback).where(Feedback.id == feedback_id))
    fb = result.scalar_one_or_none()
    if not fb:
        raise HTTPException(status_code=404, detail="Review not found")
    if fb.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own review")

    await db.delete(fb)
    await db.commit()
    optic.debug("feedback deleted: id={}", feedback_id)


@router.get("/me", response_model=list[FeedbackResponse])
async def my_feedback_received(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Feedback received on listings submitted/created by the current user."""
    optic.debug("my_feedback_received called")
    mcp_ids = list(
        (await db.execute(select(McpListing.id).where(McpListing.submitted_by == current_user.id))).scalars().all()
    )
    agent_ids = list((await db.execute(select(Agent.id).where(Agent.created_by == current_user.id))).scalars().all())
    skill_ids = list(
        (await db.execute(select(SkillListing.id).where(SkillListing.submitted_by == current_user.id))).scalars().all()
    )
    hook_ids = list(
        (await db.execute(select(HookListing.id).where(HookListing.submitted_by == current_user.id))).scalars().all()
    )
    prompt_ids = list(
        (await db.execute(select(PromptListing.id).where(PromptListing.submitted_by == current_user.id)))
        .scalars()
        .all()
    )
    sandbox_ids = list(
        (await db.execute(select(SandboxListing.id).where(SandboxListing.submitted_by == current_user.id)))
        .scalars()
        .all()
    )

    all_ids = mcp_ids + agent_ids + skill_ids + hook_ids + prompt_ids + sandbox_ids
    if not all_ids:
        return []

    result = await db.execute(
        select(Feedback).where(Feedback.listing_id.in_(all_ids)).order_by(Feedback.created_at.desc())
    )
    feedbacks = result.scalars().all()
    return [_serialize_feedback(f) for f in feedbacks]


@router.get("/summary/{listing_id}", response_model=FeedbackSummary)
async def feedback_summary(listing_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    optic.trace("listing_id={}", listing_id)
    result = await db.execute(
        select(
            func.avg(Feedback.rating).label("avg_rating"),
            func.count(Feedback.id).label("total"),
        ).where(Feedback.listing_id == listing_id)
    )
    row = result.one()
    return FeedbackSummary(
        listing_id=listing_id,
        average_rating=round(float(row.avg_rating or 0), 2),
        total_reviews=row.total,
    )


@router.get("/{listing_type}/{listing_id}", response_model=list[FeedbackResponse])
async def get_feedback(listing_type: str, listing_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get all reviews for a listing. Anonymous reviews have user_id redacted."""
    optic.trace("listing_type={}, listing_id={}", listing_type, listing_id)
    if listing_type not in LISTING_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown listing type: {listing_type}")
    result = await db.execute(
        select(Feedback)
        .where(Feedback.listing_id == listing_id, Feedback.listing_type == listing_type)
        .order_by(Feedback.created_at.desc())
    )
    return [_serialize_feedback(f) for f in result.scalars().all()]
