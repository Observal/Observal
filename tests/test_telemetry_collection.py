"""Tests for sandbox runner and config generators."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

# ── Sandbox Runner ──────────────────────────────────────────────────


class TestSandboxRunner:
    def test_now_iso_format(self):
        from observal_cli.sandbox_runner import _now_iso

        ts = _now_iso()
        assert len(ts) == 23  # YYYY-MM-DD HH:MM:SS.mmm
        assert "-" in ts and ":" in ts

    def test_max_log_bytes(self):
        from observal_cli.sandbox_runner import MAX_LOG_BYTES

        assert MAX_LOG_BYTES == 64 * 1024

    def test_send_span_no_creds(self):
        """send_span should silently return when no server_url or api_key."""
        from observal_cli.sandbox_runner import _send_span

        _send_span("", "", {"test": True})  # should not raise
        _send_span("http://localhost", "", {"test": True})
        _send_span("", "key", {"test": True})

    @patch("observal_cli.sandbox_runner.httpx.post")
    def test_send_span_posts(self, mock_post):
        from observal_cli.sandbox_runner import _send_span

        span = {"span_id": "test", "type": "sandbox_exec"}
        _send_span("http://localhost:8000", "test-key", span)
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "/api/v1/telemetry/ingest" in call_args[0][0]
        assert call_args[1]["headers"]["Authorization"] == "Bearer test-key"
        body = call_args[1]["json"]
        assert body["spans"] == [span]

    @patch("observal_cli.sandbox_runner.httpx.post", side_effect=Exception("network error"))
    def test_send_span_swallows_errors(self, mock_post):
        from observal_cli.sandbox_runner import _send_span

        _send_span("http://localhost:8000", "key", {"test": True})  # should not raise

    def _run_with_mock_docker(
        self, mock_container, sandbox_id="test-id", image="alpine:latest", command=None, timeout=300
    ):
        """Helper: run sandbox with mocked Docker SDK, return (exit_code, span_sent)."""
        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        mock_docker = MagicMock()
        mock_docker.from_env.return_value = mock_client

        captured_spans = []
        original_send = None

        with patch.dict("sys.modules", {"docker": mock_docker}):
            import importlib

            import observal_cli.sandbox_runner as sr

            importlib.reload(sr)

            original_send = sr._send_span
            sr._send_span = lambda url, key, span: captured_spans.append(span)

            try:
                sr.run_sandbox(sandbox_id, image, command, timeout)
            except SystemExit as e:
                return e.code, captured_spans[0] if captured_spans else None

        return None, None

    def test_run_sandbox_captures_logs(self):
        """Test that run_sandbox captures container logs via Docker SDK."""
        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.return_value = b"hello from container\n"
        mock_container.short_id = "abc123"
        mock_container.attrs = {"State": {"OOMKilled": False}}
        mock_container.reload.return_value = None

        exit_code, span = self._run_with_mock_docker(mock_container, command="echo hello", timeout=30)

        assert exit_code == 0
        mock_container.logs.assert_called_once_with(stdout=True, stderr=True)
        mock_container.wait.assert_called_once_with(timeout=30)
        mock_container.remove.assert_called_once_with(force=True)

        assert span is not None
        assert span["type"] == "sandbox_exec"
        assert span["output"] == "hello from container\n"
        assert span["exit_code"] == 0
        assert span["container_id"] == "abc123"
        assert span["oom_killed"] is False

    def test_run_sandbox_error_exit_code(self):
        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 1}
        mock_container.logs.return_value = b"error occurred\n"
        mock_container.short_id = "def456"
        mock_container.attrs = {"State": {"OOMKilled": False}}
        mock_container.reload.return_value = None

        exit_code, span = self._run_with_mock_docker(mock_container, command="false")

        assert exit_code == 1
        assert span["status"] == "error"
        assert span["exit_code"] == 1
        assert "exit_code=1" in span["error"]

    def test_run_sandbox_oom_detected(self):
        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 137}
        mock_container.logs.return_value = b"killed\n"
        mock_container.short_id = "oom789"
        mock_container.attrs = {"State": {"OOMKilled": True}}
        mock_container.reload.return_value = None

        exit_code, span = self._run_with_mock_docker(mock_container)

        assert span["oom_killed"] is True

    def test_run_sandbox_truncates_large_logs(self):
        from observal_cli.sandbox_runner import MAX_LOG_BYTES

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.return_value = b"x" * (MAX_LOG_BYTES + 1000)
        mock_container.short_id = "trunc"
        mock_container.attrs = {"State": {"OOMKilled": False}}
        mock_container.reload.return_value = None

        exit_code, span = self._run_with_mock_docker(mock_container)

        assert "[truncated at 64KB]" in span["output"]
        assert len(span["output"]) < MAX_LOG_BYTES + 100


# ── Config Generators ───────────────────────────────────────────────


class _MockListing:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestSandboxConfigGenerator:
    def test_basic(self):
        from services.sandbox_config_generator import generate_sandbox_config

        listing = _MockListing(id="s-123", image="python:3.12", entrypoint=None, resource_limits={})
        config = generate_sandbox_config(listing, "cursor")
        assert config["sandbox"]["command"] == "observal-sandbox-run"
        assert "--sandbox-id" in config["sandbox"]["args"]
        assert "s-123" in config["sandbox"]["args"]
        assert "--image" in config["sandbox"]["args"]
        assert "python:3.12" in config["sandbox"]["args"]

    def test_with_entrypoint(self):
        from services.sandbox_config_generator import generate_sandbox_config

        listing = _MockListing(id="s-456", image="node:18", entrypoint="npm test", resource_limits={"timeout": 60})
        config = generate_sandbox_config(listing, "kiro")
        assert "--command" in config["sandbox"]["args"]
        assert "npm test" in config["sandbox"]["args"]
        assert "--timeout" in config["sandbox"]["args"]
        assert "60" in config["sandbox"]["args"]


class TestSkillConfigGenerator:
    def test_basic(self):
        from services.skill_config_generator import generate_skill_config

        listing = _MockListing(id="sk-123", name="python-expert", git_url=None, skill_path=None)
        config = generate_skill_config(listing, "kiro")
        assert "SessionStart" in config["hooks"]
        assert "SessionEnd" in config["hooks"]
        assert config["skill"]["name"] == "python-expert"

    def test_with_git_url(self):
        from services.skill_config_generator import generate_skill_config

        listing = _MockListing(
            id="sk-456", name="test-skill", git_url="https://github.com/example/skill.git", skill_path="skills/test"
        )
        config = generate_skill_config(listing, "claude-code")
        assert config["skill"]["git_url"] == "https://github.com/example/skill.git"
        assert config["skill"]["skill_path"] == "skills/test"
        # Claude Code should have allowedEnvVars
        hook = config["hooks"]["SessionStart"][0]["hooks"][0]
        assert "allowedEnvVars" in hook


# ── Install Route Wiring ────────────────────────────────────────────


class TestInstallRouteWiring:
    """Verify install routes call config generators instead of returning stubs."""

    @pytest.mark.asyncio
    async def test_sandbox_install_uses_config_generator(self):
        from unittest.mock import AsyncMock

        from api.routes.sandbox import install_sandbox
        from schemas.sandbox import SandboxInstallRequest

        listing = _MockListing(
            id=uuid.uuid4(),
            name="test-sandbox",
            image="alpine:latest",
            entrypoint=None,
            resource_limits={},
            status=MagicMock(value="approved"),
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = listing
        mock_result.scalars.return_value.first.return_value = listing
        mock_db.execute.return_value = mock_result

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        req = SandboxInstallRequest(ide="cursor")
        resp = await install_sandbox(listing.id, req, mock_db, mock_user)
        config = resp.config_snippet
        assert "sandbox" in config
        assert config["sandbox"]["command"] == "observal-sandbox-run"

    @pytest.mark.asyncio
    async def test_skill_install_uses_config_generator(self):
        from unittest.mock import AsyncMock

        from api.routes.skill import install_skill
        from schemas.skill import SkillInstallRequest

        listing = _MockListing(
            id=uuid.uuid4(),
            name="test-skill",
            git_url=None,
            skill_path=None,
            status=MagicMock(value="approved"),
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = listing
        mock_result.scalars.return_value.first.return_value = listing
        mock_db.execute.return_value = mock_result

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        req = SkillInstallRequest(ide="claude-code")
        resp = await install_skill(listing.id, req, mock_db, mock_user)
        config = resp.config_snippet
        assert "hooks" in config
        assert "SessionStart" in config["hooks"]
