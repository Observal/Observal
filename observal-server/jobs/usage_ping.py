# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Scheduled aggregate usage reporting."""

from loguru import logger as optic


async def submit_usage_ping(ctx: dict) -> None:
    from database import async_session
    from services.usage_ping import send_scheduled_usage_ping

    async with async_session() as db:
        result = await send_scheduled_usage_ping(db)
    optic.info("usage ping job result={}", result)
