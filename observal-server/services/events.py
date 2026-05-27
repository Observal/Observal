# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Typed async event bus for core ↔ ee/ decoupling.

Core defines event types (frozen dataclasses) and fires them at natural points.
ee/ registers async handlers during startup. Handlers are fire-and-forget:
errors are logged, never raised to the emitter.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from loguru import logger as optic

logger = logging.getLogger("observal.events")

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
    is_demo: bool = False


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
class AgentLifecycleEvent(Event):
    agent_id: str
    action: str  # "registered", "updated", "deleted"
    actor_id: str
    actor_email: str


@dataclass(frozen=True, slots=True)
class AuditableAction(Event):
    """Deprecated: retained only for ee/ backward compatibility.

    The loguru-based audit middleware replaces all manual audit() calls.
    This event type is no longer emitted by core code.
    """

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
        """Decorator to register a handler for an event type.

        Usage::

            @bus.on(UserCreated)
            async def log_user(event: UserCreated) -> None:
                ...
        """

        optic.debug("on: event_type={}", event_type)

        def decorator(fn: EventHandler) -> EventHandler:
            optic.debug("decorator: fn={}", fn)
            self._handlers[event_type].append(fn)
            return fn

        return decorator

    def register(self, event_type: type[Event], handler: EventHandler) -> None:
        """Imperative registration (useful for ee/ modules)."""
        optic.debug("register: event_type={}, handler={}", event_type, handler)
        self._handlers[event_type].append(handler)

    async def emit(self, event: Event) -> None:
        """Fire all handlers for this event type.

        Errors are logged, never raised - a broken handler must not
        prevent the calling operation from completing.
        """
        optic.debug("emit: event={}", event)
        handlers = self._handlers.get(type(event), [])
        optic.debug("event emitted: {} ({} handlers)", type(event).__name__, len(handlers))
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "Event handler %s failed for %s",
                    handler.__name__,
                    type(event).__name__,
                )

    def clear(self) -> None:
        """Remove all handlers. Useful for testing."""
        optic.debug("clear called")
        self._handlers.clear()

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers across all event types."""
        optic.debug("handler_count called")
        return sum(len(h) for h in self._handlers.values())


# Module-level singleton - import from anywhere in core
bus = EventBus()
