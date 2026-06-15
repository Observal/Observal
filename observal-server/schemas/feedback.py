# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class FeedbackCreateRequest(BaseModel):
    listing_id: uuid.UUID
    listing_type: str = Field(pattern="^(mcp|agent|skill|hook|prompt|sandbox)$")
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(None, max_length=5000)
    anonymous: bool = False


class FeedbackUpdateRequest(BaseModel):
    rating: int | None = Field(None, ge=1, le=5)
    comment: str | None = Field(None, max_length=5000)
    anonymous: bool | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "FeedbackUpdateRequest":
        if self.rating is None and self.comment is None and self.anonymous is None:
            raise ValueError("At least one of rating, comment, or anonymous must be provided")
        return self


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    listing_id: uuid.UUID
    listing_type: str
    user_id: uuid.UUID | None  # None when anonymous
    rating: int
    comment: str | None
    anonymous: bool
    created_at: datetime
    updated_at: datetime | None = None
    model_config = {"from_attributes": True}


class FeedbackSummary(BaseModel):
    listing_id: uuid.UUID
    average_rating: float
    total_reviews: int
