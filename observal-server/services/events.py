# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Typed async event bus for core / ee/ decoupling.

Core defines event types (frozen dataclasses) and fires them at natural points.
ee/ registers async handlers during startup. Handlers are fire-and-forget:
errors are logged, never raised to the emitter.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from loguru import logger as optic

# Type alias for async event handlers
EventHandler = Callable[..., Coroutine[Any, Any, Any]]


# ── Event types ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Event:
    """Base class for all typed events."""


@dataclass(frozen=True, slots=True)
class UserCreated(Event):
    user_id: str
    email: str
    role: str
    name: str | None = None
    is_demo: bool = False
    org_id: str | None = None
    auth_provider: str = "local"  # "local" | "oidc" | "saml" | "scim"
    # First-touch acquisition attribution (None for SSO/SCIM-provisioned users)
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None


@dataclass(frozen=True, slots=True)
class UserDeleted(Event):
    user_id: str
    email: str


@dataclass(frozen=True, slots=True)
class LoginSuccess(Event):
    user_id: str
    email: str
    method: str  # "password", "oauth", "jwt"


@dataclass(frozen=True, slots=True)
class LoginFailure(Event):
    email: str
    method: str
    reason: str


@dataclass(frozen=True, slots=True)
class RoleChanged(Event):
    user_id: str
    email: str
    old_role: str
    new_role: str


@dataclass(frozen=True, slots=True)
class SettingsChanged(Event):
    key: str
    value: str


@dataclass(frozen=True, slots=True)
class AlertRuleChanged(Event):
    alert_id: str
    action: str  # "created", "updated", "deleted"
    actor_id: str
    actor_email: str


@dataclass(frozen=True, slots=True)
class AgentCreated(Event):
    """A new agent was registered in the registry (POST agent create)."""

    agent_id: str
    org_id: str | None
    category: str | None
    created_by: str


@dataclass(frozen=True, slots=True)
class InviteSent(Event):
    """A teammate invite was created (email-pinned or shareable link)."""

    invite_id: str
    org_id: str | None
    channel: str  # "email" | "link"
    invited_by: str


@dataclass(frozen=True, slots=True)
class InviteAccepted(Event):
    """An invited user completed signup via an invite token."""

    invite_id: str
    org_id: str | None
    user_id: str


@dataclass(frozen=True, slots=True)
class AgentLifecycleEvent(Event):
    agent_id: str
    action: str  # "registered", "updated", "deleted"
    actor_id: str
    actor_email: str


@dataclass(frozen=True, slots=True)
class AuditableAction(Event):
    """Deprecated: retained only for ee/ backward compatibility."""

    actor_id: str
    actor_email: str
    actor_role: str = ""
    action: str = ""
    resource_type: str = ""
    resource_id: str = ""
    resource_name: str = ""
    detail: str = ""


# ── Event bus ────────────────────────────────────────────────


class EventBus:
    """Simple async event bus. Core emits events, ee/ registers handlers."""

    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[EventHandler]] = defaultdict(list)

    def on(self, event_type: type[Event]) -> Callable[[EventHandler], EventHandler]:
        """Decorator to register a handler for an event type."""

        def decorator(fn: EventHandler) -> EventHandler:
            self._handlers[event_type].append(fn)
            optic.trace("registered handler '{}' for {}", fn.__name__, event_type.__name__)
            return fn

        return decorator

    def register(self, event_type: type[Event], handler: EventHandler) -> None:
        """Imperative registration (useful for ee/ modules)."""
        self._handlers[event_type].append(handler)
        optic.trace("registered handler '{}' for {}", handler.__name__, event_type.__name__)

    async def emit(self, event: Event) -> None:
        """Fire all handlers for this event type.

        Errors are logged, never raised - a broken handler must not
        prevent the calling operation from completing.
        """
        _t0 = time.perf_counter()
        event_name = type(event).__name__
        handlers = self._handlers.get(type(event), [])

        if not handlers:
            optic.trace("event {} fired but no handlers registered", event_name)
            return

        optic.debug("firing {} with {} handler(s)", event_name, len(handlers))
        failures = 0
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                failures += 1
                optic.error(
                    "handler '{}' crashed on {} - event processing continues "
                    "but this handler's side-effects are lost: {}",
                    handler.__name__,
                    event_name,
                    e,
                )

        _elapsed = (time.perf_counter() - _t0) * 1000
        if failures:
            optic.warning("{}: {}/{} handlers failed ({:.0f}ms)", event_name, failures, len(handlers), _elapsed)
        else:
            optic.trace("{}: all {} handlers completed ({:.0f}ms)", event_name, len(handlers), _elapsed)

    def clear(self) -> None:
        """Remove all handlers. Useful for testing."""
        count = sum(len(h) for h in self._handlers.values())
        self._handlers.clear()
        optic.trace("event bus cleared ({} handlers removed)", count)

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers across all event types."""
        return sum(len(h) for h in self._handlers.values())


# Module-level singleton
bus = EventBus()
