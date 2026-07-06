# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Shared router instance for admin sub-modules."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
