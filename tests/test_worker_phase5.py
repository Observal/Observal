"""Unit tests for Redis service and arq worker: Phase 5."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.redis import close, enqueue_eval, get_redis, publish

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


# --- Enqueue ---


class TestEnqueueEval:
    @pytest.mark.asyncio
    async def test_enqueues_via_arq(self):
        mock_pool = AsyncMock()
        with patch("services.redis._get_arq_pool", return_value=mock_pool):
            await enqueue_eval("agent-1", "trace-1")
            mock_pool.enqueue_job.assert_called_once_with(
                "run_eval",
                "agent-1",
                "trace-1",
                _job_id="eval:agent-1:trace-1",
            )

    @pytest.mark.asyncio
    async def test_no_trace_id_dedup_key(self):
        mock_pool = AsyncMock()
        with patch("services.redis._get_arq_pool", return_value=mock_pool):
            await enqueue_eval("agent-1")
            mock_pool.enqueue_job.assert_called_once_with(
                "run_eval",
                "agent-1",
                None,
                _job_id="eval:agent-1:all",
            )


# --- Close ---


class TestClose:
    @pytest.mark.asyncio
    async def test_disconnects_pool(self):
        mock_pool = AsyncMock()
        with patch("services.redis._pool", mock_pool):
            await close()


# --- Worker ---


class TestWorkerSettings:
    def test_registers_run_eval_function(self):
        # arq dispatches by function __name__, so removing/renaming run_eval
        # silently breaks every queued eval job. The registration must stay.
        from worker import WorkerSettings, run_eval

        assert run_eval in WorkerSettings.functions
        names = {f.__name__ for f in WorkerSettings.functions}
        assert "run_eval" in names

    def test_has_redis_settings(self):
        from worker import WorkerSettings

        assert WorkerSettings.redis_settings is not None

    def test_job_timeout(self):
        from worker import WorkerSettings

        assert WorkerSettings.job_timeout == 600

    def test_max_jobs(self):
        from worker import WorkerSettings

        assert WorkerSettings.max_jobs == 5


class TestRunEval:
    @pytest.mark.asyncio
    async def test_calls_eval_and_publishes(self):
        from worker import run_eval

        # Two scores written → published payload should report scores_written=2
        # so subscribers can show the eval result count, not just "something happened".
        scores = [{"score_id": "sc1", "value": 0.9}, {"score_id": "sc2", "value": 0.8}]

        with (
            patch(
                "services.eval.eval_engine.run_eval_on_trace",
                new_callable=AsyncMock,
                return_value=scores,
            ) as mock_run,
            patch("worker.publish", new_callable=AsyncMock) as mock_pub,
        ):
            await run_eval({}, "agent-1", "t1")

        mock_run.assert_awaited_once_with("agent-1", "t1", project_id="default")
        mock_pub.assert_awaited_once()
        channel, payload = mock_pub.call_args[0]
        assert channel == "eval:agent-1"
        assert payload == {
            "agent_id": "agent-1",
            "trace_id": "t1",
            "scores_written": 2,
        }

    @pytest.mark.asyncio
    async def test_iterates_traces_when_no_trace_id(self):
        # Without trace_id, run_eval should fan out: query traces for the agent
        # and publish one event per trace it scores.
        from worker import run_eval

        traces = [{"trace_id": "t1"}, {"trace_id": "t2"}]
        score_calls = {"t1": [{"score_id": "sc1"}], "t2": []}

        async def _fake_eval(agent_id, trace_id, project_id="default"):
            return score_calls[trace_id]

        with (
            patch("services.clickhouse.query_traces", new_callable=AsyncMock, return_value=traces),
            patch("services.eval.eval_engine.run_eval_on_trace", side_effect=_fake_eval),
            patch("worker.publish", new_callable=AsyncMock) as mock_pub,
        ):
            await run_eval({}, "agent-1")

        assert mock_pub.await_count == 2
        published = [call.args for call in mock_pub.call_args_list]
        assert published[0] == ("eval:agent-1", {"agent_id": "agent-1", "trace_id": "t1", "scores_written": 1})
        assert published[1] == ("eval:agent-1", {"agent_id": "agent-1", "trace_id": "t2", "scores_written": 0})

    @pytest.mark.asyncio
    async def test_handles_eval_error(self):
        from worker import run_eval

        # An eval crash should be swallowed (logged) and must not publish anything,
        # so subscribers don't see a partial/false-success event.
        with (
            patch(
                "services.eval.eval_engine.run_eval_on_trace",
                new_callable=AsyncMock,
                side_effect=Exception("boom"),
            ),
            patch("worker.publish", new_callable=AsyncMock) as mock_pub,
        ):
            await run_eval({}, "agent-1", "t1")  # should not raise

        mock_pub.assert_not_awaited()


# --- Docker compose ---

COMPOSE_PATH = str(Path(__file__).resolve().parent.parent / "docker" / "docker-compose.yml")


class TestDockerCompose:
    def test_redis_service_exists(self):
        import yaml

        with open(COMPOSE_PATH) as f:
            compose = yaml.safe_load(f)
        assert "observal-redis" in compose["services"]
        assert compose["services"]["observal-redis"]["image"] == "redis:7-alpine"

    def test_worker_service_runs_arq_with_worker_settings(self):
        # The worker container must launch arq against worker.WorkerSettings,
        # otherwise eval/cron jobs never run even though the container is "up".
        import yaml

        with open(COMPOSE_PATH) as f:
            compose = yaml.safe_load(f)
        worker_svc = compose["services"]["observal-worker"]
        cmd = " ".join(worker_svc["command"]) if isinstance(worker_svc["command"], list) else worker_svc["command"]
        assert "arq" in cmd
        assert "WorkerSettings" in cmd
        assert "from worker import" in cmd or "worker.WorkerSettings" in cmd

    def test_worker_depends_on_redis_healthy(self):
        # arq won't start without a reachable Redis. The compose file must wait
        # for Redis to pass its healthcheck before booting the worker, otherwise
        # the worker crash-loops on first boot.
        import yaml

        with open(COMPOSE_PATH) as f:
            compose = yaml.safe_load(f)
        deps = compose["services"]["observal-worker"]["depends_on"]
        assert "observal-redis" in deps, deps
        assert deps["observal-redis"]["condition"] == "service_healthy"

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
