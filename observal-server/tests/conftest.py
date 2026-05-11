# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

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
