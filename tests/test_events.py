# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the typed async event bus."""

import pytest

from services.events import (
    Event,
    EventBus,
    LoginFailure,
    LoginSuccess,
    RoleChanged,
    SettingsChanged,
    UserCreated,
    UserDeleted,
    bus,
)


class TestEventBus:
    def setup_method(self):
        self.bus = EventBus()

    @pytest.mark.asyncio
    async def test_emit_calls_registered_handler(self):
        received = []

        async def on_created(event: UserCreated):
            received.append(event)

        self.bus.register(UserCreated, on_created)
        event = UserCreated(user_id="1", email="a@b.com", role="admin")
        await self.bus.emit(event)

        assert len(received) == 1
        assert received[0] is event

    @pytest.mark.asyncio
    async def test_emit_calls_multiple_handlers(self):
        calls = []

        async def handler_a(event):
            calls.append("a")

        async def handler_b(event):
            calls.append("b")

        self.bus.register(UserCreated, handler_a)
        self.bus.register(UserCreated, handler_b)
        await self.bus.emit(UserCreated(user_id="1", email="x@y", role="user"))

        assert calls == ["a", "b"]

    @pytest.mark.asyncio
    async def test_emit_ignores_unrelated_event_types(self):
        received = []

        async def on_created(event):
            received.append(event)

        self.bus.register(UserCreated, on_created)
        await self.bus.emit(UserDeleted(user_id="1", email="x@y"))

        assert received == []

    @pytest.mark.asyncio
    async def test_handler_error_does_not_crash_emitter(self):
        calls = []

        async def broken_handler(event):
            raise RuntimeError("boom")

        async def healthy_handler(event):
            calls.append("ok")

        self.bus.register(UserCreated, broken_handler)
        self.bus.register(UserCreated, healthy_handler)
        await self.bus.emit(UserCreated(user_id="1", email="x@y", role="user"))

        # healthy_handler still runs despite broken_handler raising
        assert calls == ["ok"]

    @pytest.mark.asyncio
    async def test_decorator_registration(self):
        received = []

        @self.bus.on(LoginSuccess)
        async def on_login(event: LoginSuccess):
            received.append(event.method)

        await self.bus.emit(LoginSuccess(user_id="1", email="x@y", method="oauth"))
        assert received == ["oauth"]

    @pytest.mark.asyncio
    async def test_emit_with_no_handlers_is_noop(self):
        # Should not raise
        await self.bus.emit(UserDeleted(user_id="1", email="x@y"))

    def test_clear_removes_all_handlers(self):
        async def noop(event):
            pass

        self.bus.register(UserCreated, noop)
        self.bus.register(UserDeleted, noop)
        assert self.bus.handler_count == 2

        self.bus.clear()
        assert self.bus.handler_count == 0

    def test_handler_count(self):
        async def noop(event):
            pass

        assert self.bus.handler_count == 0
        self.bus.register(UserCreated, noop)
        assert self.bus.handler_count == 1
        self.bus.register(UserCreated, noop)
        assert self.bus.handler_count == 2
        self.bus.register(LoginFailure, noop)
        assert self.bus.handler_count == 3


class TestEventDataclasses:
    """Verify event types are frozen, slotted, and have expected fields."""

    def test_user_created_fields(self):
        e = UserCreated(user_id="1", email="a@b", role="admin", is_demo=True)
        assert e.user_id == "1"
        assert e.email == "a@b"
        assert e.role == "admin"
        assert e.is_demo is True

    def test_user_created_default_is_demo(self):
        e = UserCreated(user_id="1", email="a@b", role="user")
        assert e.is_demo is False

    def test_events_are_frozen(self):
        e = UserCreated(user_id="1", email="a@b", role="user")
        with pytest.raises(AttributeError):
            e.email = "changed"

    def test_all_event_types_are_subclasses(self):
        for cls in (UserCreated, UserDeleted, LoginSuccess, LoginFailure, RoleChanged, SettingsChanged):
            assert issubclass(cls, Event)

    def test_login_failure_fields(self):
        e = LoginFailure(email="a@b", method="password", reason="bad creds")
        assert e.reason == "bad creds"

    def test_role_changed_fields(self):
        e = RoleChanged(user_id="1", email="a@b", old_role="user", new_role="admin")
        assert e.old_role == "user"
        assert e.new_role == "admin"

    def test_settings_changed_fields(self):
        e = SettingsChanged(key="SECRET_KEY", value="***")
        assert e.key == "SECRET_KEY"


class TestModuleSingleton:
    """The module-level `bus` should be a working EventBus instance."""

    def test_bus_is_event_bus(self):
        assert isinstance(bus, EventBus)

    @pytest.mark.asyncio
    async def test_module_bus_works(self):
        received = []

        async def handler(event):
            received.append(event)

        bus.register(UserCreated, handler)
        try:
            await bus.emit(UserCreated(user_id="1", email="x", role="user"))
            assert len(received) == 1
        finally:
            bus.clear()
