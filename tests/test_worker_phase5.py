# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for Redis service and arq worker: Phase 5."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.redis import close, get_redis, publish

# --- Redis client ---


class TestGetRedis:
    def test_returns_redis_instance(self):
        with patch("services.redis.aioredis.ConnectionPool.from_url") as mock_pool:
            mock_pool.return_value = MagicMock()
            r = get_redis()
            assert r is not None


# --- Publish ---


class TestPublish:
    @pytest.mark.asyncio
    async def test_publishes_json(self):
        mock_redis = AsyncMock()
        with patch("services.redis.get_redis", return_value=mock_redis):
            await publish("test:channel", {"key": "value"})
            mock_redis.publish.assert_called_once_with("test:channel", json.dumps({"key": "value"}))

    @pytest.mark.asyncio
    async def test_silent_on_error(self):
        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = ConnectionError("connection refused")
        with patch("services.redis.get_redis", return_value=mock_redis):
            await publish("ch", {})  # should not raise


# --- Close ---


class TestClose:
    @pytest.mark.asyncio
    async def test_disconnects_pool(self):
        mock_pool = AsyncMock()
        with patch("services.redis._pool", mock_pool):
            await close()


# --- Worker ---


class TestWorkerSettings:
    def test_has_functions(self):
        from worker import WorkerSettings

        assert len(WorkerSettings.functions) > 0

    def test_has_redis_settings(self):
        from worker import WorkerSettings

        assert WorkerSettings.redis_settings is not None

    def test_job_timeout(self):
        from worker import WorkerSettings

        assert WorkerSettings.job_timeout == 600

    def test_max_jobs(self):
        from worker import WorkerSettings

        assert WorkerSettings.max_jobs == 5

# --- Docker compose ---

COMPOSE_PATH = str(Path(__file__).resolve().parent.parent / "docker" / "docker-compose.yml")


class TestDockerCompose:
    def test_redis_service_exists(self):
        import yaml

        with open(COMPOSE_PATH) as f:
            compose = yaml.safe_load(f)
        assert "observal-redis" in compose["services"]
        assert compose["services"]["observal-redis"]["image"] == "redis:8-alpine"

    def test_worker_service_exists(self):
        import yaml

        with open(COMPOSE_PATH) as f:
            compose = yaml.safe_load(f)
        assert "observal-worker" in compose["services"]
        assert "worker" in str(compose["services"]["observal-worker"]["command"])

    def test_redis_volume_exists(self):
        import yaml

        with open(COMPOSE_PATH) as f:
            compose = yaml.safe_load(f)
        assert "redisdata" in compose["volumes"]

    def test_api_depends_on_init(self):
        import yaml

        with open(COMPOSE_PATH) as f:
            compose = yaml.safe_load(f)
        deps = compose["services"]["observal-api"]["depends_on"]
        assert "observal-init" in deps

    def test_init_service_exists(self):
        import yaml

        with open(COMPOSE_PATH) as f:
            compose = yaml.safe_load(f)
        assert "observal-init" in compose["services"]

    def test_lb_service_exists(self):
        import yaml

        with open(COMPOSE_PATH) as f:
            compose = yaml.safe_load(f)
        assert "observal-lb" in compose["services"]
