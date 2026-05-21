# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from pydantic import BaseModel, model_validator


class RetentionConfigResponse(BaseModel):
    retention_enabled: bool
    data_retention_days: int | None
    score_retention_days: int | None
    max_trace_count: int | None
    global_retention_days: int

    model_config = {"from_attributes": True}


class RetentionConfigUpdate(BaseModel):
    retention_enabled: bool
    data_retention_days: int | None = None
    score_retention_days: int | None = None
    max_trace_count: int | None = None

    @model_validator(mode="after")
    def _validate(self):
        if self.data_retention_days is not None and self.data_retention_days < 7:
            raise ValueError("data_retention_days must be >= 7")
        if self.score_retention_days is not None and self.score_retention_days < 7:
            raise ValueError("score_retention_days must be >= 7")
        if self.max_trace_count is not None and self.max_trace_count < 1000:
            raise ValueError("max_trace_count must be >= 1000")
        if (
            self.score_retention_days is not None
            and self.data_retention_days is not None
            and self.score_retention_days < self.data_retention_days
        ):
            raise ValueError("score_retention_days must be >= data_retention_days")
        if self.retention_enabled and not self.data_retention_days and not self.max_trace_count:
            raise ValueError(
                "At least one of data_retention_days or max_trace_count is required when enabling retention"
            )
        return self
