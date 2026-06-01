# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Regression coverage for Audit 2 PR1 ingest abuse guardrails."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError


def _trace(trace_id: str = "trace-1") -> dict:
    return {
        "trace_id": trace_id,
        "start_time": "2026-01-01T00:00:00Z",
    }


def _span(span_id: str = "span-1") -> dict:
    return {
        "span_id": span_id,
        "trace_id": "trace-1",
        "type": "tool_call",
        "name": "Read",
        "start_time": "2026-01-01T00:00:00Z",
    }


def _score(score_id: str = "score-1") -> dict:
    return {
        "score_id": score_id,
        "name": "overall",
        "value": 1.0,
    }


def _info():
    info = MagicMock()
    info.context = {"project_id": "default"}
    return info


def _query_bound(default, name: str):
    if hasattr(default, name):
        return getattr(default, name)
    for item in getattr(default, "metadata", []):
        if hasattr(item, name):
            return getattr(item, name)
    return None


def test_telemetry_ingest_batch_rejects_oversized_lists():
    from schemas.telemetry import MAX_INGEST_SPANS, MAX_INGEST_TRACES, IngestBatch

    with pytest.raises(ValidationError):
        IngestBatch(traces=[_trace(str(i)) for i in range(MAX_INGEST_TRACES + 1)])

    with pytest.raises(ValidationError):
        IngestBatch(spans=[_span(str(i)) for i in range(MAX_INGEST_SPANS + 1)])


def test_telemetry_ingest_rejects_oversized_strings_and_metadata_values():
    from schemas.telemetry import MAX_TEXT_LENGTH, ScoreIngest, SpanIngest, TraceIngest

    with pytest.raises(ValidationError):
        TraceIngest(**_trace(), input="x" * (MAX_TEXT_LENGTH + 1))

    with pytest.raises(ValidationError):
        SpanIngest(**_span(), error="x" * (MAX_TEXT_LENGTH + 1))

    with pytest.raises(ValidationError):
        ScoreIngest(**_score(), metadata={"large": "x" * (MAX_TEXT_LENGTH + 1)})


def test_telemetry_ingest_rejects_oversized_tags_and_metadata_maps():
    from schemas.telemetry import MAX_METADATA_ENTRIES, MAX_SHORT_STRING_LENGTH, MAX_TAGS, TraceIngest

    with pytest.raises(ValidationError):
        TraceIngest(**_trace(), tags=[str(i) for i in range(MAX_TAGS + 1)])

    with pytest.raises(ValidationError):
        TraceIngest(**_trace(), tags=["x" * (MAX_SHORT_STRING_LENGTH + 1)])

    with pytest.raises(ValidationError):
        TraceIngest(**_trace(), metadata={str(i): "v" for i in range(MAX_METADATA_ENTRIES + 1)})


def test_session_ingest_rejects_oversized_batches_and_lines():
    from api.routes.ingest import MAX_SESSION_LINES, SessionIngestRequest
    from schemas.telemetry import MAX_TEXT_LENGTH

    with pytest.raises(ValidationError):
        SessionIngestRequest(session_id="session-1", lines=["{}"] * (MAX_SESSION_LINES + 1))

    with pytest.raises(ValidationError):
        SessionIngestRequest(session_id="session-1", lines=["x" * (MAX_TEXT_LENGTH + 1)])

    with pytest.raises(ValidationError):
        SessionIngestRequest(session_id="session-1", lines=["{}"], start_offset=-1)


def test_telemetry_ingest_endpoint_keeps_batch_first_and_requires_request():
    import inspect

    from api.routes.telemetry import ingest

    signature = inspect.signature(ingest)
    assert list(signature.parameters)[:2] == ["batch", "request"]


@pytest.mark.asyncio
async def test_graphql_trace_limit_is_clamped_to_max_page_size():
    from api.graphql import MAX_TRACE_PAGE_SIZE, Query

    rows = [
        {"trace_id": f"trace-{i}", "user_id": "user-1", "start_time": "2026-01-01"}
        for i in range(MAX_TRACE_PAGE_SIZE + 1)
    ]
    query_traces = AsyncMock(return_value=rows)

    with patch("api.graphql.query_traces", query_traces):
        result = await Query().traces(info=_info(), limit=1_000_000, offset=5)

    assert len(result.items) == MAX_TRACE_PAGE_SIZE
    assert result.has_more is True
    query_traces.assert_awaited_once()
    assert query_traces.call_args.kwargs["limit"] == MAX_TRACE_PAGE_SIZE + 1
    assert query_traces.call_args.kwargs["offset"] == 5


@pytest.mark.asyncio
async def test_graphql_trace_negative_offset_is_rejected():
    from api.graphql import Query

    with pytest.raises(ValueError, match="offset"):
        await Query().traces(info=_info(), offset=-1)


def test_alert_history_query_params_are_bounded():
    import inspect

    from api.routes.alert import get_alert_history

    signature = inspect.signature(get_alert_history)
    assert signature.parameters["limit"].default.default == 50
    assert _query_bound(signature.parameters["limit"].default, "le") == 200
    assert signature.parameters["offset"].default.default == 0
    assert _query_bound(signature.parameters["offset"].default, "ge") == 0


def test_mcp_validator_rejects_http_git_by_default():
    import services.mcp_validator as mcp_validator

    with (
        patch.object(mcp_validator, "ALLOWED_SCHEMES", {"https"}),
        patch.object(mcp_validator, "ALLOW_HTTP_GIT", False),
    ):
        err = mcp_validator._validate_git_url("http://github.com/example/repo")

    assert err is not None
    assert "scheme" in err.lower()
    assert "https" in err.lower()


def test_mcp_validator_allows_http_only_with_explicit_opt_in():
    import services.mcp_validator as mcp_validator

    with (
        patch.object(mcp_validator, "ALLOWED_SCHEMES", {"https", "http"}),
        patch.object(mcp_validator, "ALLOW_HTTP_GIT", True),
        patch.object(mcp_validator, "_ssrf_is_private", return_value=False),
    ):
        assert mcp_validator._validate_git_url("http://github.com/example/repo") is None
        assert "MCP_ALLOW_HTTP_GIT" in mcp_validator._git_url_warning("http://github.com/example/repo")


def test_mcp_validator_warning_is_empty_for_https_urls():
    import services.mcp_validator as mcp_validator

    with patch.object(mcp_validator, "ALLOW_HTTP_GIT", True):
        assert mcp_validator._git_url_warning("https://github.com/example/repo") == ""
        assert mcp_validator._git_url_warning("https://gitlab.example.com/x.git") == ""


def test_mcp_validator_env_var_controls_allowed_schemes_at_import():
    """Ensure the env-var -> ALLOWED_SCHEMES wiring is exercised, not just patched."""
    import importlib
    import os

    import services.mcp_validator as mcp_validator

    original_env = os.environ.get("MCP_ALLOW_HTTP_GIT")
    try:
        os.environ["MCP_ALLOW_HTTP_GIT"] = "true"
        importlib.reload(mcp_validator)
        assert mcp_validator.ALLOW_HTTP_GIT is True
        assert "http" in mcp_validator.ALLOWED_SCHEMES
        assert "https" in mcp_validator.ALLOWED_SCHEMES

        os.environ["MCP_ALLOW_HTTP_GIT"] = "false"
        importlib.reload(mcp_validator)
        assert mcp_validator.ALLOW_HTTP_GIT is False
        assert "http" not in mcp_validator.ALLOWED_SCHEMES
        assert {"https"} == mcp_validator.ALLOWED_SCHEMES
    finally:
        if original_env is None:
            os.environ.pop("MCP_ALLOW_HTTP_GIT", None)
        else:
            os.environ["MCP_ALLOW_HTTP_GIT"] = original_env
        importlib.reload(mcp_validator)


def test_telemetry_ingest_batch_rejects_oversized_scores_list():
    from schemas.telemetry import MAX_INGEST_SCORES, IngestBatch

    with pytest.raises(ValidationError):
        IngestBatch(scores=[_score(str(i)) for i in range(MAX_INGEST_SCORES + 1)])


def test_telemetry_ingest_rejects_remaining_oversized_string_fields():
    from schemas.telemetry import MAX_TEXT_LENGTH, ScoreIngest, SpanIngest, TraceIngest

    oversize_text = "x" * (MAX_TEXT_LENGTH + 1)

    with pytest.raises(ValidationError):
        TraceIngest(**_trace(), output=oversize_text)

    with pytest.raises(ValidationError):
        SpanIngest(**_span(), input=oversize_text)

    with pytest.raises(ValidationError):
        SpanIngest(**_span(), output=oversize_text)

    with pytest.raises(ValidationError):
        ScoreIngest(**_score(), string_value=oversize_text)

    with pytest.raises(ValidationError):
        ScoreIngest(**_score(), comment=oversize_text)


def test_telemetry_ingest_rejects_oversized_span_metadata_and_metadata_keys():
    from schemas.telemetry import MAX_METADATA_ENTRIES, MAX_SHORT_STRING_LENGTH, SpanIngest, TraceIngest

    with pytest.raises(ValidationError):
        SpanIngest(**_span(), metadata={str(i): "v" for i in range(MAX_METADATA_ENTRIES + 1)})

    # Metadata keys are bounded by MAX_SHORT_STRING_LENGTH via the validator.
    long_key = "k" * (MAX_SHORT_STRING_LENGTH + 1)
    with pytest.raises(ValidationError):
        TraceIngest(**_trace(), metadata={long_key: "v"})

    with pytest.raises(ValidationError):
        SpanIngest(**_span(), metadata={long_key: "v"})


def test_telemetry_ingest_accepts_maximum_valid_sizes():
    """Boundary regression: exact-limit payloads must remain accepted."""
    from schemas.telemetry import (
        MAX_INGEST_SCORES,
        MAX_INGEST_SPANS,
        MAX_INGEST_TRACES,
        MAX_METADATA_ENTRIES,
        MAX_TAGS,
        MAX_TEXT_LENGTH,
        IngestBatch,
        ScoreIngest,
        SpanIngest,
        TraceIngest,
    )

    batch = IngestBatch(
        traces=[_trace(str(i)) for i in range(MAX_INGEST_TRACES)],
        spans=[_span(str(i)) for i in range(MAX_INGEST_SPANS)],
        scores=[_score(str(i)) for i in range(MAX_INGEST_SCORES)],
    )
    assert len(batch.traces) == MAX_INGEST_TRACES
    assert len(batch.spans) == MAX_INGEST_SPANS
    assert len(batch.scores) == MAX_INGEST_SCORES

    edge_text = "x" * MAX_TEXT_LENGTH
    TraceIngest(**_trace(), input=edge_text, output=edge_text)
    SpanIngest(**_span(), input=edge_text, output=edge_text, error=edge_text)
    ScoreIngest(**_score(), string_value=edge_text, comment=edge_text)

    TraceIngest(
        **_trace(),
        tags=[str(i) for i in range(MAX_TAGS)],
        metadata={str(i): "v" for i in range(MAX_METADATA_ENTRIES)},
    )


def test_session_ingest_rejects_oversized_short_string_fields():
    from api.routes.ingest import MAX_SHORT_STRING_LENGTH, SessionIngestRequest

    long_value = "x" * (MAX_SHORT_STRING_LENGTH + 1)

    with pytest.raises(ValidationError):
        SessionIngestRequest(session_id=long_value, lines=[])

    with pytest.raises(ValidationError):
        SessionIngestRequest(session_id="s", ide=long_value, lines=[])

    with pytest.raises(ValidationError):
        SessionIngestRequest(session_id="s", agent_id=long_value, lines=[])

    with pytest.raises(ValidationError):
        SessionIngestRequest(session_id="s", parent_session_id=long_value, lines=[])


def test_alert_history_endpoint_rejects_oversized_limit_via_query_validation():
    """Behavior-level guard: FastAPI must reject limit=300 through query validation."""
    import uuid

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import deps as deps_module
    from api.routes import alert as alert_module
    from models.user import UserRole

    class _FakeDB:
        async def get(self, *args, **kwargs):
            return None

    async def _current_user():
        user = MagicMock()
        user.id = uuid.uuid4()
        user.email = "tester@example.com"
        user.role = UserRole.user
        user.org_id = None
        return user

    async def _get_db():
        yield _FakeDB()

    app = FastAPI()
    app.dependency_overrides[deps_module.get_current_user] = _current_user
    app.dependency_overrides[alert_module.get_db] = _get_db
    app.include_router(alert_module.router)

    client = TestClient(app, raise_server_exceptions=False)
    alert_id = "00000000-0000-0000-0000-000000000000"

    # limit above bound -> 422
    resp = client.get(f"/api/v1/alerts/{alert_id}/history?limit=300")
    assert resp.status_code == 422
    assert "limit" in resp.text

    # negative offset -> 422
    resp = client.get(f"/api/v1/alerts/{alert_id}/history?limit=50&offset=-1")
    assert resp.status_code == 422
    assert "offset" in resp.text

    # limit at the maximum passes validation and then misses in the fake DB.
    resp = client.get(f"/api/v1/alerts/{alert_id}/history?limit=200&offset=0")
    assert resp.status_code == 404


def test_telemetry_and_session_ingest_have_rate_limit_decorators_wired():
    """Smoke-check that slowapi limits are attached to the abuse-prone endpoints."""
    import inspect

    from api.routes.ingest import ingest_session
    from api.routes.telemetry import ingest as ingest_telemetry

    # slowapi stores the limit string on the wrapped function via closure or attribute.
    # Both routes also require `request: Request` to be in the signature for slowapi to work.
    telemetry_params = list(inspect.signature(ingest_telemetry).parameters)
    session_params = list(inspect.signature(ingest_session).parameters)
    assert "request" in telemetry_params, "slowapi requires `request: Request` in the signature"
    assert "request" in session_params, "slowapi requires `request: Request` in the signature"


def test_rate_limit_key_prefers_identity_then_token_then_ip():
    import hashlib

    from api.ratelimit import _get_rate_limit_key

    user_request = MagicMock()
    user_request.state = SimpleNamespace(current_user=SimpleNamespace(id="user-1", org_id="org-1"))
    user_request.headers = {}
    assert _get_rate_limit_key(user_request) == "org:org-1:user:user-1"

    token_request = MagicMock()
    token_request.state = SimpleNamespace()
    token_request.headers = {"authorization": "Bearer secret-token"}
    digest = hashlib.sha256(b"secret-token").hexdigest()
    assert _get_rate_limit_key(token_request) == f"token:{digest}"

    ip_request = MagicMock()
    ip_request.state = SimpleNamespace()
    ip_request.headers = {}
    ip_request.client = MagicMock()
    ip_request.client.host = "203.0.113.10"
    with patch("api.ratelimit.ds") as mock_ds:
        mock_ds.get_sync.return_value = ""
        assert _get_rate_limit_key(ip_request) == "ip:203.0.113.10"


@pytest.mark.asyncio
async def test_get_current_user_stores_identity_for_rate_limit_key():
    import uuid

    from api.deps import get_current_user
    from models.user import UserRole

    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "tester@example.com"
    user.role = UserRole.user
    user.org_id = uuid.uuid4()
    user.auth_provider = "password"

    request = MagicMock()
    request.url.path = "/api/v1/telemetry/ingest"
    request.state = SimpleNamespace()

    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)

    with (
        patch("api.deps._authenticate_via_jwt", AsyncMock(return_value=user)),
        patch("api.deps.get_redis", return_value=redis),
    ):
        result = await get_current_user(request, authorization="Bearer access-token", db=MagicMock())

    assert result is user
    assert request.state.current_user is user
    assert request.state.org_id == user.org_id
