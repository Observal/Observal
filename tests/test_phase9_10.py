# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for Phase 9 (Score Unification) and Phase 10 (CLI Updates)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_current_user, get_db
from api.routes.feedback import router as feedback_router
from models.user import User

# --- Phase 9: Score Unification ---


def _make_user():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = "admin"
    u.org_id = None
    return u


def _make_app(user):
    app = FastAPI()
    app.include_router(feedback_router)
    app.dependency_overrides[get_current_user] = lambda: user
    # Mock DB session
    mock_db = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=uuid.uuid4())  # listing exists
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(
        side_effect=lambda fb: setattr(fb, "id", uuid.uuid4()) or setattr(fb, "created_at", "2026-01-01")
    )
    app.dependency_overrides[get_db] = lambda: mock_db
    return app


class TestFeedbackDualWrite:
    @pytest.mark.asyncio
    async def test_writes_to_clickhouse_scores(self):
        user = _make_user()
        app = _make_app(user)
        listing_id = str(uuid.uuid4())

        with patch("api.routes.feedback.insert_scores", new_callable=AsyncMock) as mock_insert:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post(
                    "/api/v1/feedback",
                    json={
                        "listing_id": listing_id,
                        "listing_type": "mcp",
                        "rating": 5,
                        "comment": "Great tool!",
                    },
                )
            assert r.status_code == 200
            mock_insert.assert_called_once()
            scores = mock_insert.call_args[0][0]
            assert len(scores) == 1
            assert scores[0]["name"] == "user_rating"
            assert scores[0]["source"] == "api"
            assert scores[0]["value"] == 5.0
            assert scores[0]["comment"] == "Great tool!"
            assert scores[0]["mcp_id"] == listing_id

    @pytest.mark.asyncio
    async def test_agent_feedback_sets_agent_id(self):
        user = _make_user()
        app = _make_app(user)
        listing_id = str(uuid.uuid4())

        with patch("api.routes.feedback.insert_scores", new_callable=AsyncMock) as mock_insert:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post(
                    "/api/v1/feedback",
                    json={
                        "listing_id": listing_id,
                        "listing_type": "agent",
                        "rating": 4,
                    },
                )
            scores = mock_insert.call_args[0][0]
            assert scores[0]["agent_id"] == listing_id
            assert scores[0]["mcp_id"] is None

    @pytest.mark.asyncio
    async def test_clickhouse_failure_doesnt_break_request(self):
        user = _make_user()
        app = _make_app(user)

        with patch("api.routes.feedback.insert_scores", new_callable=AsyncMock, side_effect=Exception("CH down")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post(
                    "/api/v1/feedback",
                    json={
                        "listing_id": str(uuid.uuid4()),
                        "listing_type": "mcp",
                        "rating": 3,
                    },
                )
            assert r.status_code == 200  # request still succeeds


# --- Phase 10: CLI Updates ---


class TestCLICommands:
    def test_downgrade_requires_version_flag(self):
        from typer.testing import CliRunner

        from observal_cli.main import app as cli_app

        runner = CliRunner()
        result = runner.invoke(cli_app, ["self", "downgrade"])
        assert result.exit_code == 1
        assert "--version" in result.output or "version" in result.output.lower()

    def test_upgrade_command_exists(self):
        from typer.testing import CliRunner

        from observal_cli.main import app as cli_app

        runner = CliRunner()
        result = runner.invoke(cli_app, ["self", "upgrade", "--help"])
        assert result.exit_code == 0
        assert "Upgrade" in result.output or "upgrade" in result.output

    def test_traces_command_exists(self):
        from typer.testing import CliRunner

        from observal_cli.main import app as cli_app

        runner = CliRunner()
        result = runner.invoke(cli_app, ["ops", "traces", "--help"])
        assert result.exit_code == 0
        assert "trace" in result.output.lower()

    def test_spans_command_exists(self):
        from typer.testing import CliRunner

        from observal_cli.main import app as cli_app

        runner = CliRunner()
        result = runner.invoke(cli_app, ["ops", "spans", "--help"])
        assert result.exit_code == 0
        assert "span" in result.output.lower() or "trace" in result.output.lower()
