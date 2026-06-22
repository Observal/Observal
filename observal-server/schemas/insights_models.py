# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from pydantic import BaseModel, Field


class LiteLLMProvider(BaseModel):
    id: str
    label: str
    model_count: int


class LiteLLMModel(BaseModel):
    model_id: str
    litellm_provider: str
    litellm_model: str
    mode: str
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None
    deprecation_date: str | None = None
    deprecated: bool = False
    capabilities: list[str] = Field(default_factory=list)


class LiteLLMProviderList(BaseModel):
    providers: list[LiteLLMProvider]


class LiteLLMModelList(BaseModel):
    provider: str
    models: list[LiteLLMModel]
