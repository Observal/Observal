# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Test username auto-generation and collision handling."""

import re

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from models.base import Base
from models.user import User
from services.username_generator import generate_unique_username

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,30}[a-z0-9]$")


@pytest.fixture()
async def db():
    """Provide a test async SQLite database session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_unique_username_basic(db: AsyncSession) -> None:
    """Test basic username generation from email."""
    username = await generate_unique_username("john@example.com", db)
    assert username == "john"
    assert 3 <= len(username) <= 32


@pytest.mark.asyncio
async def test_generate_unique_username_with_dots(db: AsyncSession) -> None:
    """Test that dots are replaced with hyphens."""
    username = await generate_unique_username("john.doe@example.com", db)
    assert username == "john-doe"


@pytest.mark.asyncio
async def test_generate_unique_username_collision_handling(db: AsyncSession) -> None:
    """Test collision handling with deterministic suffixes."""
    user1 = User(
        email="john@example.com",
        username="john",
        name="John One",
    )
    db.add(user1)
    await db.commit()

    # Generate username for "john" from different email should get suffix
    username2 = await generate_unique_username("john.smith@example.com", db)
    assert username2.startswith("john-")
    assert len(username2) > len("john")
    assert username2 != "john"

    # Verify it's unique
    result = await db.execute(select(User).where(User.username == username2))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_generate_unique_username_deterministic(db: AsyncSession) -> None:
    """Test that same email generates same username on retry."""
    username1 = await generate_unique_username("test@example.com", db)
    username2 = await generate_unique_username("test@example.com", db)
    assert username1 == username2


@pytest.mark.asyncio
async def test_generate_unique_username_special_chars(db: AsyncSession) -> None:
    """Test sanitization of special characters."""
    username = await generate_unique_username("john+tag@example.com", db)
    assert all(c.isalnum() or c == "-" for c in username)


@pytest.mark.asyncio
async def test_generate_unique_username_length_limit(db: AsyncSession) -> None:
    """Test that username respects 32 character database limit."""
    username = await generate_unique_username("verylongemailaddressname@example.com", db)
    assert len(username) <= 32


@pytest.mark.asyncio
async def test_generate_unique_username_regex_valid(db: AsyncSession) -> None:
    """Test that generated username matches validation regex."""
    username = await generate_unique_username("test@example.com", db)
    assert USERNAME_RE.match(username), f"Generated username '{username}' doesn't match regex"


@pytest.mark.asyncio
async def test_generate_unique_username_multiple_collisions(db: AsyncSession) -> None:
    """Test handling of multiple collisions."""
    for i in range(3):
        user = User(
            email=f"john{i}@example.com",
            username=f"john{i}" if i > 0 else "john",
            name=f"John {i}",
        )
        db.add(user)
    await db.commit()

    username = await generate_unique_username("john.test@example.com", db)
    assert username.startswith("john-")

    result = await db.execute(select(User).where(User.username == username))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_generate_unique_username_short_email(db: AsyncSession) -> None:
    """Test that single-char email prefix still generates valid username."""
    username = await generate_unique_username("j@example.com", db)
    assert USERNAME_RE.match(username), f"Generated username '{username}' doesn't match regex"
    assert len(username) >= 3


@pytest.mark.asyncio
async def test_generate_unique_username_numeric_only(db: AsyncSession) -> None:
    """Test numeric-only email prefix."""
    username = await generate_unique_username("123@example.com", db)
    assert all(c.isalnum() or c == "-" for c in username)
    assert len(username) >= 3


@pytest.mark.asyncio
async def test_generate_unique_username_all_special_chars(db: AsyncSession) -> None:
    """Test email with all special characters in local part."""
    username = await generate_unique_username("+++@example.com", db)
    assert USERNAME_RE.match(username), f"Generated username '{username}' doesn't match regex"
