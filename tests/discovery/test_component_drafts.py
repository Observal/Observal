# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-FileCopyrightText: 2026 VishnuM049 <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from unittest.mock import Mock

import pytest

from observal_cli import component_drafts
from observal_cli.component_drafts import (
    DraftPayloadError,
    build_hook_draft_payload,
    build_mcp_draft_payload,
    build_skill_draft_payload,
    create_hook_draft,
    create_mcp_draft,
    create_skill_draft,
)


def test_mcp_draft_builder_preserves_command_payload_and_copies_nested_values() -> None:
    payload = {
        "name": "search",
        "version": "0.1.0",
        "description": "Search server",
        "owner": "alice",
        "category": "general",
        "command": "npx",
        "args": ["-y", "@acme/search"],
        "environment_variables": [{"name": "API_KEY", "description": "Search key", "required": True}],
        "supported_harnesses": ["kiro"],
    }

    built = build_mcp_draft_payload(payload)

    assert built == payload
    assert built is not payload
    assert built["args"] is not payload["args"]
    assert built["environment_variables"] is not payload["environment_variables"]


def test_mcp_draft_builder_preserves_header_declarations() -> None:
    payload = {
        "name": "remote",
        "url": "https://mcp.example.test",
        "headers": [{"name": "Authorization", "description": "Bearer token", "required": True}],
    }

    assert build_mcp_draft_payload(payload) == payload


def test_mcp_draft_builder_rejects_literal_header_values() -> None:
    payload = {
        "name": "remote",
        "url": "https://mcp.example.test",
        "headers": [{"name": "Authorization", "value": "Bearer secret"}],
    }

    with pytest.raises(DraftPayloadError, match="unsupported fields"):
        build_mcp_draft_payload(payload)


def test_mcp_draft_builder_normalizes_legacy_http_transport() -> None:
    payload = build_mcp_draft_payload({"name": "remote", "url": "https://example.test/mcp", "transport": "http"})

    assert payload["transport"] == "streamable-http"


def test_skill_draft_builder_preserves_registry_direct_payload() -> None:
    payload = {
        "name": "review",
        "version": "1.0.0",
        "description": "Review changes",
        "owner": "alice",
        "delivery_mode": "registry_direct",
        "skill_path": "/",
        "skill_md_content": "---\nname: review\n---\n# Review\n",
        "script_content": "#!/bin/sh\n",
        "script_filename": "run.sh",
        "task_type": "general",
        "target_agents": ["agent-a"],
        "supported_harnesses": ["claude-code", "pi"],
    }

    assert build_skill_draft_payload(payload) == payload


def test_hook_draft_builder_preserves_handler_and_source_payload() -> None:
    payload = {
        "name": "guard",
        "version": "1.0.0",
        "description": "Guard writes",
        "owner": "alice",
        "event": "PreToolUse",
        "execution_mode": "blocking",
        "priority": 100,
        "handler_type": "command",
        "handler_config": {"command": "guard.sh", "timeout": 10},
        "scope": "agent",
        "tool_filter": ["Write"],
        "source_url": "https://github.com/acme/hooks",
        "source_ref": "main",
        "source_path": "hooks/guard",
        "requirements": ["bash"],
        "supported_harnesses": ["kiro"],
    }

    built = build_hook_draft_payload(payload)

    assert built == payload
    assert built["handler_config"] is not payload["handler_config"]


@pytest.mark.parametrize(
    ("builder", "payload", "message"),
    [
        (build_mcp_draft_payload, {"command": "npx"}, "field 'name'"),
        (build_mcp_draft_payload, {"name": "x", "args": "--flag"}, "field 'args'"),
        (build_mcp_draft_payload, {"name": "x", "transport": "websocket"}, "must be one of"),
        (
            build_mcp_draft_payload,
            {"name": "x", "transport": "stdio", "url": "https://example.test/mcp"},
            "forbids URL",
        ),
        (
            build_mcp_draft_payload,
            {"name": "x", "transport": "sse", "command": "npx"},
            "forbids process",
        ),
        (
            build_mcp_draft_payload,
            {"name": "x", "environment_variables": [{"name": "TOKEN", "required": "yes"}]},
            "required flag",
        ),
        (build_skill_draft_payload, {"name": "x", "target_agents": [1]}, "field 'target_agents'"),
        (build_skill_draft_payload, {"name": "x", "slash_command": "../unsafe"}, "invalid format"),
        (build_hook_draft_payload, {"name": "x", "handler_config": []}, "field 'handler_config'"),
        (build_hook_draft_payload, {"name": "x", "priority": True}, "field 'priority'"),
        (
            build_skill_draft_payload,
            {"name": "x", "supported_harnesses": ["not-a-harness"]},
            "unknown harness",
        ),
    ],
)
def test_draft_builders_reject_schema_incompatible_payloads(builder, payload, message) -> None:
    with pytest.raises(DraftPayloadError, match=message):
        builder(payload)


@pytest.mark.parametrize(
    ("create", "endpoint", "payload"),
    [
        (create_mcp_draft, "/api/v1/mcps/draft", {"name": "search", "command": "npx"}),
        (
            create_skill_draft,
            "/api/v1/skills/draft",
            {"name": "review", "delivery_mode": "registry_direct", "skill_md_content": "# Review"},
        ),
        (
            create_hook_draft,
            "/api/v1/hooks/draft",
            {"name": "guard", "event": "PreToolUse", "handler_config": {"command": "guard"}},
        ),
    ],
)
def test_draft_services_validate_and_perform_exactly_one_post(monkeypatch, create, endpoint, payload) -> None:
    response = {"id": "draft-1", "status": "draft"}
    post = Mock(return_value=response)
    monkeypatch.setattr(component_drafts.client, "post", post)

    assert create(payload) is response
    post.assert_called_once_with(endpoint, payload)


def test_invalid_draft_never_posts(monkeypatch) -> None:
    post = Mock(side_effect=AssertionError("invalid draft must not mutate"))
    monkeypatch.setattr(component_drafts.client, "post", post)

    with pytest.raises(DraftPayloadError):
        create_hook_draft({"name": "guard", "handler_config": []})

    post.assert_not_called()
