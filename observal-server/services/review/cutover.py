# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""The single submit-to-review path. The caller commits all rows together."""

from models.agent import AgentStatus
from models.mcp import ListingStatus
from models.review import ReviewState
from services.review.decisions import _head, open_or_push, sync_state
from services.review.notifications import deliver_event


async def submit_for_review(db, subject_type, subject, version, actor_id, *, message=None):
    review = await open_or_push(db, subject_type, subject, version, actor_id, message=message)
    # New releases of an approved listing leave its published version visible.
    # A draft/rejected listing, however, must enter the pending queue when its
    # first review opens (or when changes are resubmitted).
    if subject.status in (ListingStatus.draft, ListingStatus.rejected, ListingStatus.changes_requested):
        subject.status = AgentStatus.pending if subject_type == "agent" else ListingStatus.pending
    revision = await _head(db, review)
    if revision.number == 1:
        await sync_state(db, review, actor_id=actor_id)
    event = "published" if review.state == ReviewState.published else "opened" if revision.number == 1 else "revision"
    await deliver_event(db, review, event, actor_id, revision=revision.number)
    return review
