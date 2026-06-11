# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Fire-and-forget HTTP client for the GTM dossier-builder signup webhook.

Only enabled on the public observal.io instance (``GTM_SIGNUP_WEBHOOK_ENABLED``).
Private / enterprise deployments must leave this off: the payload intentionally
carries signup email and name for GTM prospect matching.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import httpx
from loguru import logger as optic

from config import settings
from services.ssrf_guard import is_private_url


def is_enabled() -> bool:
    """Master gate: explicit enable flag only (default off)."""
    return bool(settings.GTM_SIGNUP_WEBHOOK_ENABLED)


def _build_payload(*, email: str, name: str | None, company: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"email": email.strip().lower()}
    if name:
        payload["name"] = name
    if company:
        payload["company"] = company
    return payload


def _sign_body(body: bytes) -> dict[str, str]:
    secret = settings.GTM_SIGNUP_WEBHOOK_SECRET
    if not secret:
        return {}
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-GTM-Signature": f"sha256={digest}"}


async def notify_gtm_signup(
    *,
    email: str,
    name: str | None,
    company: str | None,
) -> None:
    """POST signup details to the GTM engine. Never raises."""
    if not is_enabled():
        return

    url = settings.GTM_SIGNUP_WEBHOOK_URL
    if is_private_url(url):
        optic.warning("gtm signup webhook blocked: URL resolves to private network")
        return

    payload = _build_payload(email=email, name=name, company=company)
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", **_sign_body(body)}

    try:
        async with httpx.AsyncClient(timeout=settings.GTM_SIGNUP_WEBHOOK_TIMEOUT_SEC) as client:
            resp = await client.post(url, content=body, headers=headers)
        if resp.status_code >= 400:
            optic.warning("gtm signup webhook returned HTTP {}", resp.status_code)
    except Exception as e:
        optic.warning("gtm signup webhook failed: {}", e)


def schedule_gtm_signup_notify(
    *,
    email: str,
    name: str | None,
    company: str | None,
) -> None:
    """Queue a background delivery so signup handlers never await GTM latency."""
    if not is_enabled():
        return
    asyncio.create_task(  # noqa: RUF006
        notify_gtm_signup(email=email, name=name, company=company),
        name="gtm-signup-webhook",
    )
