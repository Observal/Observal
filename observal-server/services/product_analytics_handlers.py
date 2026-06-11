# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Event-bus subscribers mapping domain events to PostHog product events.

The full PostHog integration lives in this module plus
``services.product_analytics`` so it can be found and audited in one place.

Event contract (consumed verbatim by the GTM engine - names and property
keys must not change):

- ``UserCreated``    -> ``user_signed_up``   {utm_source, utm_medium,
                                              utm_campaign, auth_provider, org_id}
- ``AgentCreated``   -> ``agent_registered`` {workspace_id, agent_id, agent_type}
- ``InviteSent``     -> ``invite_sent``      {workspace_id, invite_channel}
- ``InviteAccepted`` -> ``invite_accepted``  {workspace_id}

Policy decisions (documented per issue #1418):

- Demo accounts are excluded entirely.
- SCIM/SAML-provisioned users ARE counted as signups, with null UTMs
  (the GTM engine buckets them as "organic").
- Invite acceptances emit ``user_signed_up`` with ``utm_source="invite"``
  (forced server-side in the accept route) plus ``invite_accepted``.
- Orgs with ``trace_privacy=true`` emit nothing.
"""

from __future__ import annotations

import uuid

from loguru import logger as optic
from sqlalchemy import select

import services.product_analytics as product_analytics
from services.events import AgentCreated, InviteAccepted, InviteSent, UserCreated, bus


async def org_trace_private(org_id: str | None) -> bool:
    """True when the org opted into trace privacy (=> drop all telemetry)."""
    if not org_id:
        return False
    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return False

    from database import async_session
    from models.organization import Organization

    try:
        async with async_session() as db:
            private = await db.scalar(select(Organization.trace_privacy).where(Organization.id == org_uuid))
        return bool(private)
    except Exception as e:
        # Fail closed: if we cannot verify the privacy setting, drop the event.
        optic.debug("trace_privacy lookup failed for org {}: {}", org_id, e)
        return True


@bus.on(UserCreated)
async def _capture_user_signed_up(event: UserCreated) -> None:
    if not product_analytics.is_enabled():
        return
    if event.is_demo:
        return
    if await org_trace_private(event.org_id):
        return

    await product_analytics.capture(
        event.user_id,
        "user_signed_up",
        {
            "utm_source": event.utm_source,
            "utm_medium": event.utm_medium,
            "utm_campaign": event.utm_campaign,
            "auth_provider": event.auth_provider,
            "org_id": event.org_id,
        },
    )


@bus.on(AgentCreated)
async def _capture_agent_registered(event: AgentCreated) -> None:
    if not product_analytics.is_enabled():
        return
    if await org_trace_private(event.org_id):
        return

    await product_analytics.capture(
        event.created_by,
        "agent_registered",
        {
            "workspace_id": event.org_id,
            "agent_id": event.agent_id,
            "agent_type": event.category,
        },
    )


@bus.on(InviteSent)
async def _capture_invite_sent(event: InviteSent) -> None:
    if not product_analytics.is_enabled():
        return
    if await org_trace_private(event.org_id):
        return

    await product_analytics.capture(
        event.invited_by,
        "invite_sent",
        {
            "workspace_id": event.org_id,
            "invite_channel": event.channel,
        },
    )


@bus.on(InviteAccepted)
async def _capture_invite_accepted(event: InviteAccepted) -> None:
    if not product_analytics.is_enabled():
        return
    if await org_trace_private(event.org_id):
        return

    await product_analytics.capture(
        event.user_id,
        "invite_accepted",
        {
            "workspace_id": event.org_id,
        },
    )
