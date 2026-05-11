# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FeedbackCreateRequest(BaseModel):
    listing_id: uuid.UUID
    listing_type: str = Field(pattern="^(mcp|agent|skill|hook|prompt|sandbox)$")
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(None, max_length=5000)


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    listing_id: uuid.UUID
    listing_type: str
    user_id: uuid.UUID
    rating: int
    comment: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class FeedbackSummary(BaseModel):
    listing_id: uuid.UUID
    average_rating: float
    total_reviews: int
