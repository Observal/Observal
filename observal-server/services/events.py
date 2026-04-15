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

        def decorator(fn: EventHandler) -> EventHandler:
            self._handlers[event_type].append(fn)
            return fn

        return decorator

    def register(self, event_type: type[Event], handler: EventHandler) -> None:
        """Imperative registration (useful for ee/ modules)."""
        self._handlers[event_type].append(handler)

    async def emit(self, event: Event) -> None:
        """Fire all handlers for this event type.

        Errors are logged, never raised — a broken handler must not
        prevent the calling operation from completing.
        """
        handlers = self._handlers.get(type(event), [])
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
        self._handlers.clear()

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers across all event types."""
        return sum(len(h) for h in self._handlers.values())


# Module-level singleton — import from anywhere in core
bus = EventBus()
