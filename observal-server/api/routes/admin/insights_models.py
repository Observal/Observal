# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Admin settings endpoints for the Insights LiteLLM model picker."""

from fastapi import Depends, HTTPException, Query
from loguru import logger as optic

from api.deps import require_role
from api.routes.admin._router import router
from models.user import User, UserRole
from schemas.insights_models import LiteLLMModelList, LiteLLMProviderList
from services.litellm_model_catalog import list_models as list_litellm_models
from services.litellm_model_catalog import list_providers as list_litellm_providers


@router.get("/insights/models/providers", response_model=LiteLLMProviderList)
async def insights_model_providers(current_user: User = Depends(require_role(UserRole.admin))):
    """Return LiteLLM providers with Insights-compatible models in the vendored snapshot."""
    optic.trace("user_id={}", current_user.id)
    return LiteLLMProviderList(providers=list_litellm_providers())


@router.get("/insights/models", response_model=LiteLLMModelList)
async def insights_models(
    provider: str = Query(..., min_length=1),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Return Insights-compatible models for one LiteLLM provider."""
    optic.trace("user_id={}, provider={}", current_user.id, provider)
    rows = list_litellm_models(provider)
    if not rows:
        raise HTTPException(status_code=404, detail="Provider not found")
    return LiteLLMModelList(provider=provider, models=rows)
