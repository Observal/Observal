# SPDX-FileCopyrightText: 2026 Nav-Prak <naveenprakaasam@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Telemetry endpoint redaction regression coverage.

Client telemetry can carry secrets in structured metadata, tags, score fields,
and payload strings. These tests assert ingest sanitizes those surfaces before
anything is handed to the ClickHouse insert layer.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes.telemetry import router
from models.user import User, UserRole
from services.secrets_redactor import REDACTED

SECRET_VALUE = "abcdef1234567890abcdef1234567890"


def _make_user():
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.role = UserRole.user
    user.org_id = None
    return user


def _app_with_user(user):
    from api.deps import get_current_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    return app


@pytest.mark.asyncio
async def test_telemetry_ingest_redacts_trace_metadata_tags_and_payloads():
    app = _app_with_user(_make_user())

    with patch("api.routes.telemetry.insert_traces", new_callable=AsyncMock) as mock_insert:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/telemetry/ingest",
                json={
                    "traces": [
                        {
                            "trace_id": "trace-redact",
                            "start_time": "2026-01-01 00:00:00.000",
                            "metadata": {"request": f"password={SECRET_VALUE}"},
                            "tags": [f"auth_token: {SECRET_VALUE}"],
                            "input": f"api_key={SECRET_VALUE}",
                            "output": f"token={SECRET_VALUE}",
                        }
                    ]
                },
            )

    assert response.status_code == 200
    row = mock_insert.call_args.args[0][0]
    serialized = json.dumps(row, default=str)
    assert SECRET_VALUE not in serialized
    assert REDACTED in serialized


@pytest.mark.asyncio
async def test_telemetry_ingest_redacts_span_metadata_and_error_fields():
    app = _app_with_user(_make_user())

    with patch("api.routes.telemetry.insert_spans", new_callable=AsyncMock) as mock_insert:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/telemetry/ingest",
                json={
                    "spans": [
                        {
                            "span_id": "span-redact",
                            "trace_id": "trace-redact",
                            "type": "tool_call",
                            "name": "Read",
                            "start_time": "2026-01-01 00:00:00.000",
                            "input": f"client_secret={SECRET_VALUE}",
                            "output": f"access_token={SECRET_VALUE}",
                            "error": f"Authorization: Bearer {SECRET_VALUE}",
                            "metadata": {"headers": f"X-API-Key: {SECRET_VALUE}"},
                        }
                    ]
                },
            )

    assert response.status_code == 200
    row = mock_insert.call_args.args[0][0]
    serialized = json.dumps(row, default=str)
    assert SECRET_VALUE not in serialized
    assert REDACTED in serialized


@pytest.mark.asyncio
async def test_telemetry_ingest_redacts_score_strings_comments_and_metadata():
    app = _app_with_user(_make_user())

    with patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as mock_insert:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/telemetry/ingest",
                json={
                    "scores": [
                        {
                            "score_id": "score-redact",
                            "name": "quality",
                            "value": 0.9,
                            "string_value": f"password={SECRET_VALUE}",
                            "comment": f"client_secret={SECRET_VALUE}",
                            "metadata": {"prompt": f"auth_token={SECRET_VALUE}"},
                        }
                    ]
                },
            )

    assert response.status_code == 200
    row = mock_insert.call_args.args[0][0]
    serialized = json.dumps(row, default=str)
    assert SECRET_VALUE not in serialized
    assert REDACTED in serialized
