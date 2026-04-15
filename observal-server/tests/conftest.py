"""Shared fixtures for JWT / auth tests."""

import os
import uuid

import pytest

# Override settings before any app code imports them
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")


@pytest.fixture()
def user_id():
    return str(uuid.uuid4())


@pytest.fixture()
def user_role():
    return "admin"
