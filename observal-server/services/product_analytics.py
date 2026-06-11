# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Product analytics (PostHog) capture - public-instance only, OFF by default.

This is the single integration point with PostHog Cloud. Gating rules
(all must be true for anything to be sent):

1. ``PRODUCT_ANALYTICS_ENABLED=true``  (default: false)
2. ``POSTHOG_API_KEY`` is non-empty
3. The acting user's org has ``trace_privacy=false`` (checked per event
   by :func:`org_trace_private` in the handlers module)

Private / enterprise deployments must leave this off: enabling it sends
usage events to PostHog Cloud US (subprocessor). See
``docs/self-hosting/telemetry.md`` for the full event contract.

PII rules: distinct_id is always the user UUID. Properties contain only
UUIDs and enum-like strings - never email, name, username, prompts, or
trace content. ``$ip`` is explicitly nulled so PostHog never stores or
geolocates request IPs.
"""

from __future__ import annotations

from typing import Any

from loguru import logger as optic

from config import settings

_client: Any = None
_init_attempted = False


def is_enabled() -> bool:
    """Master gate: analytics flag on AND an API key configured."""
    return bool(settings.PRODUCT_ANALYTICS_ENABLED and settings.POSTHOG_API_KEY)


def _get_client() -> Any:
    """Lazily build the PostHog client. Returns None when gated off."""
    global _client, _init_attempted
    if _init_attempted:
        return _client
    _init_attempted = True

    if not is_enabled():
        return None

    try:
        from posthog import Posthog

        _client = Posthog(
            project_api_key=settings.POSTHOG_API_KEY,
            host=settings.POSTHOG_HOST,
        )
        optic.info("product analytics enabled (PostHog host: {})", settings.POSTHOG_HOST)
    except Exception as e:  # missing package, bad config - never break the app
        optic.warning("product analytics unavailable: {}", e)
        _client = None
    return _client


async def capture(distinct_id: str, event: str, properties: dict | None = None) -> None:
    """Fire-and-forget event capture. Never raises, never blocks a request.

    The posthog client enqueues to an in-memory queue flushed by a
    background thread, so this is a cheap synchronous enqueue. Any client
    failure (bad key, network down) is swallowed and logged at debug level.
    """
    client = _get_client()
    if client is None:
        return

    props = dict(properties or {})
    # Never geolocate / store IPs (server-side captures would otherwise
    # attribute the API server's IP, or a forwarded user IP, to the person).
    props["$ip"] = None

    try:
        client.capture(event=event, distinct_id=distinct_id, properties=props)
    except Exception as e:
        optic.debug("product analytics capture failed for {}: {}", event, e)


def shutdown() -> None:
    """Flush the queue and stop the client. Called from app lifespan teardown."""
    global _client, _init_attempted
    if _client is not None:
        try:
            _client.shutdown()
        except Exception as e:
            optic.debug("product analytics shutdown error: {}", e)
    _client = None
    _init_attempted = False
