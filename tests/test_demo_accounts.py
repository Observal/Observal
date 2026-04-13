"""Tests for demo account seeding and cleanup."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.user import User, UserRole
from services.events import UserCreated, bus


def _make_user(role=UserRole.user, is_demo=False, email="test@test.com"):
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.role = role
    user.is_demo = is_demo
    return user


class TestSeedDemoAccounts:
    @pytest.mark.asyncio
    async def test_seeds_when_no_real_users(self):
        from services.demo_accounts import seed_demo_accounts

        db = AsyncMock()
        # First call: real_count=0, then per-tier exists checks return 0
        db.scalar = AsyncMock(side_effect=[0, 0, 0, 0, 0])
        db.commit = AsyncMock()

        with patch("services.demo_accounts.settings") as mock_settings:
            mock_settings.DEMO_SUPER_ADMIN_EMAIL = "super@demo.local"
            mock_settings.DEMO_SUPER_ADMIN_PASSWORD = "super-pass"
            mock_settings.DEMO_ADMIN_EMAIL = "admin@demo.local"
            mock_settings.DEMO_ADMIN_PASSWORD = "admin-pass"
            mock_settings.DEMO_REVIEWER_EMAIL = "reviewer@demo.local"
            mock_settings.DEMO_REVIEWER_PASSWORD = "reviewer-pass"
            mock_settings.DEMO_USER_EMAIL = "user@demo.local"
            mock_settings.DEMO_USER_PASSWORD = "user-pass"

            count = await seed_demo_accounts(db)

        assert count == 4
        assert db.add.call_count == 4
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_when_real_users_exist(self):
        from services.demo_accounts import seed_demo_accounts

        db = AsyncMock()
        db.scalar = AsyncMock(return_value=1)  # real_count=1

        with patch("services.demo_accounts.settings") as mock_settings:
            mock_settings.DEMO_SUPER_ADMIN_EMAIL = "super@demo.local"
            mock_settings.DEMO_SUPER_ADMIN_PASSWORD = "pass"

            count = await seed_demo_accounts(db)

        assert count == 0
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_demo_env_vars(self):
        from services.demo_accounts import seed_demo_accounts

        db = AsyncMock()
        db.scalar = AsyncMock(return_value=0)  # no real users

        with patch("services.demo_accounts.settings") as mock_settings:
            mock_settings.DEMO_SUPER_ADMIN_EMAIL = None
            mock_settings.DEMO_SUPER_ADMIN_PASSWORD = None
            mock_settings.DEMO_ADMIN_EMAIL = None
            mock_settings.DEMO_ADMIN_PASSWORD = None
            mock_settings.DEMO_REVIEWER_EMAIL = None
            mock_settings.DEMO_REVIEWER_PASSWORD = None
            mock_settings.DEMO_USER_EMAIL = None
            mock_settings.DEMO_USER_PASSWORD = None

            count = await seed_demo_accounts(db)

        assert count == 0

    @pytest.mark.asyncio
    async def test_idempotent_skips_existing(self):
        from services.demo_accounts import seed_demo_accounts

        db = AsyncMock()
        # real_count=0, super_admin exists=1 (skip), admin exists=0 (create)
        db.scalar = AsyncMock(side_effect=[0, 1, 0])
        db.commit = AsyncMock()

        with patch("services.demo_accounts.settings") as mock_settings:
            mock_settings.DEMO_SUPER_ADMIN_EMAIL = "super@demo.local"
            mock_settings.DEMO_SUPER_ADMIN_PASSWORD = "pass"
            mock_settings.DEMO_ADMIN_EMAIL = "admin@demo.local"
            mock_settings.DEMO_ADMIN_PASSWORD = "pass"
            mock_settings.DEMO_REVIEWER_EMAIL = None
            mock_settings.DEMO_REVIEWER_PASSWORD = None
            mock_settings.DEMO_USER_EMAIL = None
            mock_settings.DEMO_USER_PASSWORD = None

            count = await seed_demo_accounts(db)

        assert count == 1  # Only admin created, super_admin skipped


class TestCleanupDemoAccounts:
    @pytest.mark.asyncio
    async def test_super_admin_deletes_all_demos(self):
        from services.demo_accounts import cleanup_demo_accounts

        mock_result = MagicMock()
        mock_result.rowcount = 4
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()

        deleted = await cleanup_demo_accounts(db, UserRole.super_admin)

        assert deleted == 4
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_admin_deletes_only_demo_admin(self):
        from services.demo_accounts import cleanup_demo_accounts

        mock_result = MagicMock()
        mock_result.rowcount = 1
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()

        deleted = await cleanup_demo_accounts(db, UserRole.admin)
        assert deleted == 1

    @pytest.mark.asyncio
    async def test_no_demos_returns_zero(self):
        from services.demo_accounts import cleanup_demo_accounts

        mock_result = MagicMock()
        mock_result.rowcount = 0
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        deleted = await cleanup_demo_accounts(db, UserRole.user)
        assert deleted == 0
        db.commit.assert_not_awaited()


class TestEventDrivenCleanup:
    """Verify the bus handler triggers cleanup on UserCreated."""

    def setup_method(self):
        # Import to ensure the @bus.on(UserCreated) handler is registered
        import services.demo_accounts  # noqa: F401

    @pytest.mark.asyncio
    async def test_real_user_triggers_cleanup(self):
        with patch("services.demo_accounts.cleanup_demo_accounts", new_callable=AsyncMock) as mock_cleanup:
            mock_db = AsyncMock()
            with patch("database.async_session") as mock_session_factory:
                mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

                await bus.emit(
                    UserCreated(
                        user_id="abc",
                        email="real@company.com",
                        role="admin",
                        is_demo=False,
                    )
                )

            mock_cleanup.assert_awaited_once_with(mock_db, UserRole.admin)

    @pytest.mark.asyncio
    async def test_demo_user_does_not_trigger_cleanup(self):
        with patch("services.demo_accounts.cleanup_demo_accounts", new_callable=AsyncMock) as mock_cleanup:
            await bus.emit(
                UserCreated(
                    user_id="abc",
                    email="demo@demo.local",
                    role="user",
                    is_demo=True,
                )
            )

            mock_cleanup.assert_not_awaited()
