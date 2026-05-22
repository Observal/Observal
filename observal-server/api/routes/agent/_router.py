# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared router instance for agent sub-modules."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
