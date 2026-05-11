# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import datetime

from pydantic import BaseModel

from models.insight_report import InsightReportStatus


class GenerateInsightRequest(BaseModel):
    period_days: int = 14


class InsightReportListItem(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    status: InsightReportStatus
    period_start: datetime
    period_end: datetime
    sessions_analyzed: int
    created_at: datetime
    completed_at: datetime | None
    model_config = {"from_attributes": True}


class InsightReportResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    triggered_by: uuid.UUID | None
    status: InsightReportStatus
    period_start: datetime
    period_end: datetime
    metrics: dict | None
    narrative: dict | None
    sessions_analyzed: int
    llm_model_used: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    # V2+ fields
    previous_report_id: uuid.UUID | None = None
    aggregated_data: dict | None = None
    report_version: int = 3
    model_config = {"from_attributes": True}
