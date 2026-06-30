# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Boot-time configuration: env vars required to start the server.

All runtime-tunable settings have been moved to the Settings page
(stored in enterprise_config table, accessed via services.dynamic_settings).

Only infrastructure, crypto, and auth middleware vars remain here.
"""

import os
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Infrastructure
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/observal"
    CLICKHOUSE_URL: str = "clickhouse://localhost:8123/observal"
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_SOCKET_TIMEOUT: float = 2.0
    REDIS_MAX_CONNECTIONS: int = 200

    # Crypto
    SECRET_KEY: str = "change-me-to-a-random-string"

    # JWT key management (boot-time, keys loaded once at startup)
    JWT_SIGNING_ALGORITHM: str = "ES256"
    JWT_KEY_DIR: str = "~/.observal/keys"
    JWT_KEY_PASSWORD: str | None = None

    # Connection pool sizing (boot-time, pool created once at startup)
    DB_POOL_SIZE: int = 30
    DB_MAX_OVERFLOW: int = 50
    CLICKHOUSE_MAX_CONNECTIONS: int = 100
    CLICKHOUSE_MAX_KEEPALIVE: int = 100
    CLICKHOUSE_TIMEOUT: float = 10.0

    # Logging (boot-time, configured before event loop starts)
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"

    SKIP_DDL_ON_STARTUP: bool = False

    # Demo accounts (boot-time, needed to bootstrap first login)
    SEED_DEMO_ACCOUNTS: bool = True
    DEMO_SUPER_ADMIN_EMAIL: str | None = None
    DEMO_SUPER_ADMIN_PASSWORD: str | None = None
    DEMO_ADMIN_EMAIL: str | None = None
    DEMO_ADMIN_PASSWORD: str | None = None
    DEMO_REVIEWER_EMAIL: str | None = None
    DEMO_REVIEWER_PASSWORD: str | None = None
    DEMO_USER_EMAIL: str | None = None
    DEMO_USER_PASSWORD: str | None = None

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

# Derived: True when an enterprise license key is configured.
# Used as the replacement for the removed DEPLOYMENT_MODE env var.
# Feature availability is still gated by ee.license.is_feature_licensed();
# this flag only controls "should we attempt to load ee/ packages."
HAS_LICENSE: bool = bool(os.environ.get("OBSERVAL_LICENSE_KEY", ""))
