# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Event-bus subscriber: notify the GTM dossier builder on real signups.

Fires once per ``UserCreated`` on the public instance when
``GTM_SIGNUP_WEBHOOK_ENABLED=true``. Skips demo accounts, SCIM
provisioning, localhost bootstrap signups, and orgs with trace privacy on.

PostHog product analytics is handled separately in
``services.product_analytics_handlers``.
"""

from __future__ import annotations

import uuid

from loguru import logger as optic
from sqlalchemy import select

import services.gtm_signup_webhook as gtm_signup_webhook
from services.events import UserCreated, bus
from services.product_analytics_handlers import org_trace_private


async def resolve_org_name(org_id: str | None) -> str | None:
    """Load organization display name when the signup is org-scoped."""
    if not org_id:
        return None
    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return None

    from database import async_session
    from models.organization import Organization

    try:
        async with async_session() as db:
            name = await db.scalar(select(Organization.name).where(Organization.id == org_uuid))
        return name or None
    except Exception as e:
        optic.debug("org name lookup failed for org {}: {}", org_id, e)
        return None


def _is_bootstrap_signup(email: str) -> bool:
    """Local-mode bootstrap uses admin@localhost and must not hit GTM."""
    return email.strip().lower().endswith("@localhost")


@bus.on(UserCreated)
async def on_user_created_gtm(event: UserCreated) -> None:
    if not gtm_signup_webhook.is_enabled():
        return
    if event.is_demo:
        return
    if event.auth_provider == "scim":
        return
    if _is_bootstrap_signup(event.email):
        return
    if await org_trace_private(event.org_id):
        return

    company = await resolve_org_name(event.org_id)
    gtm_signup_webhook.schedule_gtm_signup_notify(
        email=event.email,
        name=event.name,
        company=company,
    )
