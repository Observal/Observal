# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-FileCopyrightText: 2026 VishnuM049 <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import uuid
from unittest.mock import Mock

import pytest

from observal_cli import agent_drafts
from observal_cli.agent_drafts import (
    AgentDefinitionError,
    agent_definition_from_candidate,
    build_agent_draft_payload,
    build_agent_payload,
    build_discovered_agent_draft_payload,
    create_agent_draft,
    validate_agent_definition,
)
from observal_cli.discovery.models import (
    ComponentType,
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoveryScope,
    ProviderKind,
)
from observal_cli.harness import DiscoveredAgent


def _candidate(
    *,
    name: str = "Review Helper",
    model_name: str = "claude-sonnet-4",
    prompt: str = "Review every change carefully.",
    harness: str = "kiro",
) -> DiscoveryCandidate:
    evidence = DiscoveryEvidence(
        component=DiscoveredAgent(name, "Reviews changes", model_name, prompt, "/project/AGENT.md"),
        provider=ProviderKind.HARNESS,
        scope=DiscoveryScope.PROJECT,
        harness=harness,
        display_path="<project>/AGENT.md",
    )
    return DiscoveryCandidate(
        component_type=ComponentType.AGENT,
        local_name=name,
        correlation_identity=None,
        launch_fingerprint=None,
        evidence=[evidence],
    )


def _definition() -> dict:
    return {
        "name": "review-helper",
        "version": "0.1.0",
        "description": "Reviews changes",
        "owner": "alice",
        "model_name": "claude-sonnet-4",
        "model_config_json": {},
        "models_by_harness": {},
        "prompt": "Review every change carefully.",
        "supported_harnesses": ["kiro"],
        "components": [],
        "external_mcps": [],
        "success_criteria": None,
    }


def test_discovered_agent_converts_to_validated_in_memory_definition() -> None:
    candidate = _candidate()

    definition = agent_definition_from_candidate(candidate, owner="alice")

    assert definition == _definition()
    assert validate_agent_definition(definition) == definition


def test_discovered_agent_uses_yaml_payload_builder_and_draft_default_version() -> None:
    payload = build_discovered_agent_draft_payload(_candidate(), owner="alice")

    assert payload == {
        "name": "review-helper",
        "version": "0.1.0",
        "description": "Reviews changes",
        "category": None,
        "owner": "alice",
        "model_name": "claude-sonnet-4",
        "model_config_json": {},
        "models_by_harness": {},
        "prompt": "Review every change carefully.",
        "supported_harnesses": ["kiro"],
        "mcp_server_ids": [],
        "components": [],
        "external_mcps": [],
        "success_criteria": None,
    }
    assert payload == build_agent_payload(_definition(), default_version="0.1.0")


def test_agent_payload_preserves_supported_server_fields() -> None:
    definition = _definition()
    definition.update(
        {
            "category": "testing",
            "model_config_json": {"temperature": 0.2},
            "mcp_server_ids": ["mcp-1"],
            "external_mcps": [{"name": "local", "command": "python", "args": ["server.py"]}],
        }
    )

    payload = build_agent_payload(definition)

    assert payload["category"] == "testing"
    assert payload["model_config_json"] == {"temperature": 0.2}
    assert payload["mcp_server_ids"] == ["mcp-1"]
    assert payload["external_mcps"] == [{"name": "local", "command": "python", "args": ["server.py"]}]


def test_discovered_agent_combines_harnesses_for_identical_evidence() -> None:
    candidate = _candidate(harness="kiro")
    candidate.evidence.append(
        DiscoveryEvidence(
            component=DiscoveredAgent(
                "Review Helper",
                "Reviews changes",
                "claude-sonnet-4",
                "Review every change carefully.",
                "/home/AGENT.md",
            ),
            provider=ProviderKind.HARNESS,
            scope=DiscoveryScope.USER,
            harness="claude-code",
            display_path="~/.claude/agents/review-helper.md",
        )
    )

    definition = agent_definition_from_candidate(candidate, owner="alice")

    assert definition["supported_harnesses"] == ["claude-code", "kiro"]


@pytest.mark.parametrize(
    ("candidate", "field"),
    [
        (_candidate(model_name=""), "model_name"),
        (_candidate(prompt=""), "prompt"),
    ],
)
def test_discovered_agent_rejects_incomplete_model_or_prompt(candidate, field) -> None:
    with pytest.raises(AgentDefinitionError) as raised:
        build_discovered_agent_draft_payload(candidate, owner="alice")

    assert raised.value.field == field


def test_agent_draft_accepts_prompt_component_without_inline_prompt() -> None:
    from schemas.agent import AgentCreateRequest

    definition = _definition()
    definition["prompt"] = ""
    definition["components"] = [{"component_type": "prompt", "component_id": str(uuid.uuid4())}]

    payload = build_agent_draft_payload(definition)
    server_request = AgentCreateRequest.model_validate(payload)

    assert payload["prompt"] == ""
    assert payload["components"] == definition["components"]
    assert server_request.components[0].component_type == "prompt"


@pytest.mark.parametrize(
    ("candidate", "owner", "field"),
    [
        (_candidate(), "", "owner"),
        (_candidate(name="!!!"), "alice", "name"),
    ],
)
def test_discovered_agent_rejects_missing_owner_or_invalid_name(candidate, owner, field) -> None:
    with pytest.raises(AgentDefinitionError) as raised:
        agent_definition_from_candidate(candidate, owner=owner)

    assert raised.value.field == field


def test_discovered_agent_rejects_ambiguous_definition_evidence() -> None:
    candidate = _candidate()
    candidate.evidence.append(
        DiscoveryEvidence(
            component=DiscoveredAgent("Review Helper", "Different", "gpt-4o", "Other prompt", "/other.md"),
            provider=ProviderKind.HARNESS,
            scope=DiscoveryScope.USER,
            harness="cursor",
            display_path="~/.cursor/agents/review-helper.md",
        )
    )

    with pytest.raises(AgentDefinitionError) as raised:
        agent_definition_from_candidate(candidate, owner="alice")

    assert raised.value.field == "evidence"


def test_agent_draft_service_posts_once_without_writing_local_state(monkeypatch) -> None:
    response = {"id": "draft-1", "status": "draft"}
    post = Mock(return_value=response)
    monkeypatch.setattr(agent_drafts.client, "post", post)

    assert create_agent_draft(_definition()) is response
    post.assert_called_once_with("/api/v1/agents/draft", build_agent_draft_payload(_definition()))


def test_invalid_agent_draft_never_posts(monkeypatch) -> None:
    post = Mock(side_effect=AssertionError("invalid draft must not mutate"))
    monkeypatch.setattr(agent_drafts.client, "post", post)
    definition = _definition()
    definition["prompt"] = ""

    with pytest.raises(AgentDefinitionError) as raised:
        create_agent_draft(definition)

    assert raised.value.field == "prompt"
    post.assert_not_called()
