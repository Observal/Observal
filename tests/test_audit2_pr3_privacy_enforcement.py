# SPDX-FileCopyrightText: 2026 Nav-Prak <naveenprakaasam@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Ingest privacy-mode enforcement.

Secret redaction is always applied; the org privacy_mode controls how much raw
payload survives ingest. These tests cover the redaction helpers and the
telemetry/session ingest paths under each of the four modes.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes.telemetry import router
from models.user import UserRole
from services.privacy import PREVIEW_LEN, redact_payload_text, redact_structured
from services.secrets_redactor import REDACTED

SECRET = "password=abcdef1234567890abcdef1234567890"


# ---------------------------------------------------------------------------
# Helper-level
# ---------------------------------------------------------------------------


def test_payload_full_keeps_secret_redacted_content():
    out = redact_payload_text(SECRET, "full")
    assert REDACTED in out
    assert "abcdef1234567890" not in out


def test_payload_redacted_truncates_to_preview_length():
    out = redact_payload_text("x" * (PREVIEW_LEN + 100), "redacted")
    assert len(out) == PREVIEW_LEN


def test_payload_metadata_only_and_disabled_raw_drop_content():
    assert redact_payload_text(SECRET, "metadata_only") == ""
    assert redact_payload_text(SECRET, "disabled_raw") == ""


def test_payload_none_preserved_in_every_mode():
    for mode in ("full", "redacted", "metadata_only", "disabled_raw"):
        assert redact_payload_text(None, mode) is None


def test_structured_kept_and_redacted_unless_disabled_raw():
    md = {"api_key": "plain-value", "region": "us"}
    for mode in ("full", "redacted", "metadata_only"):
        out = redact_structured(md, mode)
        assert out["api_key"] == REDACTED  # key-name redaction still applies
        assert out["region"] == "us"


def test_structured_disabled_raw_empties_container_by_type():
    assert redact_structured({"api_key": "x"}, "disabled_raw") == {}
    assert redact_structured(["a", "b"], "disabled_raw") == []
    assert redact_structured(None, "disabled_raw") is None


# ---------------------------------------------------------------------------
# Telemetry ingest path
# ---------------------------------------------------------------------------


def _user(mode):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.role = UserRole.user
    user.org_id = None
    user._privacy_mode = mode
    return user


def _app(user):
    from api.deps import get_current_user
    from api.ratelimit import limiter

    # /ingest is rate-limited (Redis-backed) upstream; disable it for these
    # unit tests, which run without Redis.
    limiter.enabled = False
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    return app


async def _ingest_trace(mode):
    app = _app(_user(mode))
    with patch("api.routes.telemetry.insert_traces", new_callable=AsyncMock) as mock_insert:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/telemetry/ingest",
                json={
                    "traces": [
                        {
                            "trace_id": "t1",
                            "start_time": "2026-01-01 00:00:00.000",
                            "metadata": {"region": "us"},
                            "tags": ["team-a"],
                            "input": "prompt body",
                            "output": "completion body",
                        }
                    ]
                },
            )
    assert resp.status_code == 200
    return mock_insert.call_args.args[0][0]


@pytest.mark.asyncio
async def test_telemetry_metadata_only_drops_payloads_keeps_metadata():
    row = await _ingest_trace("metadata_only")
    assert row["input"] == ""
    assert row["output"] == ""
    assert row["metadata"] == {"region": "us"}
    assert row["tags"] == ["team-a"]


@pytest.mark.asyncio
async def test_telemetry_disabled_raw_drops_payloads_and_metadata():
    row = await _ingest_trace("disabled_raw")
    assert row["input"] == ""
    assert row["output"] == ""
    assert row["metadata"] == {}
    assert row["tags"] == []


@pytest.mark.asyncio
async def test_telemetry_full_keeps_payloads_and_metadata():
    row = await _ingest_trace("full")
    assert row["input"] == "prompt body"
    assert row["output"] == "completion body"
    assert row["metadata"] == {"region": "us"}


# ---------------------------------------------------------------------------
# Session ingest path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expect_raw_line,expect_preview",
    [
        ("full", True, True),
        ("redacted", False, True),
        ("metadata_only", False, False),
        ("disabled_raw", False, False),
    ],
)
async def test_session_privacy_modes(mode, expect_raw_line, expect_preview):
    from services.session_ingest import ingest_session_lines

    raw_line = json.dumps(
        {
            "type": "user",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "uuid": "line-1",
            "message": {"content": "hello world transcript content"},
        }
    )

    with (
        patch("services.session_ingest.query_existing_for_dedup", AsyncMock(return_value=(set(), set()))),
        patch("services.session_ingest.insert_session_events", new_callable=AsyncMock) as mock_insert,
    ):
        result = await ingest_session_lines(
            session_id="s1",
            project_id="p1",
            user_id="u1",
            agent_id=None,
            agent_version=None,
            ide="claude-code",
            lines=[raw_line],
            privacy_mode=mode,
        )

    assert result.ingested == 1
    row = mock_insert.call_args.args[0][0]
    assert bool(row["raw_line"]) == expect_raw_line
    assert bool(row["content_preview"]) == expect_preview
    # Classification + identifiers are retained in every mode.
    assert row["event_type"]
    assert row["content_length"] > 0
