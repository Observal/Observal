# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-FileCopyrightText: 2026 VishnuM049 <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Reusable agent-definition validation and draft creation services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from packaging.version import InvalidVersion, Version

from observal_cli import client
from observal_cli.constants import AGENT_NAME_REGEX, VALID_HARNESSES
from observal_cli.discovery.models import ComponentType, DiscoveryCandidate
from observal_cli.harness import DiscoveredAgent
from observal_shared.registry_slug import slugify

if TYPE_CHECKING:
    from observal_cli.discovery.models import DiscoveryEvidence


@dataclass(eq=False)
class AgentDefinitionError(ValueError):
    """A field in an agent definition cannot be safely validated."""

    field: str
    message: str

    def __post_init__(self) -> None:
        super().__init__(self.message)


def validate_agent_name(name: object) -> str:
    """Validate an agent name using the existing YAML authoring rules."""

    if not isinstance(name, str) or not name:
        raise AgentDefinitionError("name", "Agent name is required.")
    if len(name) > 64:
        raise AgentDefinitionError("name", "Agent name must be at most 64 characters.")
    if not AGENT_NAME_REGEX.match(name):
        raise AgentDefinitionError(
            "name",
            "Must start with a letter/digit and contain only lowercase letters, digits, hyphens, underscores.",
        )
    return name


def normalize_agent_version(value: object, *, default: str = "1.0.0") -> str:
    """Apply the semantic-version normalization used by YAML workflows."""

    raw = str(value or default)
    try:
        return str(Version(raw))
    except InvalidVersion as error:
        raise AgentDefinitionError("version", f"Invalid semantic version: {raw}.") from error


def validate_agent_harnesses(values: object) -> list[str]:
    """Validate and copy an agent's supported harness list."""

    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise AgentDefinitionError("supported_harnesses", "Agent supported_harnesses must be a list of names.")
    invalid = [value for value in values if value not in VALID_HARNESSES]
    if invalid:
        raise AgentDefinitionError("supported_harnesses", f"Unknown harness: {invalid[0]}.")
    return list(values)


def validate_agent_definition(definition: Mapping[str, Any], *, default_version: str = "1.0.0") -> dict[str, Any]:
    """Validate an in-memory definition using the YAML build workflow rules."""

    if not isinstance(definition, Mapping):
        raise AgentDefinitionError("definition", "Agent definition must be a mapping.")
    data = deepcopy(dict(definition))
    data["name"] = validate_agent_name(data.get("name"))
    data["version"] = normalize_agent_version(data.get("version"), default=default_version)
    data["supported_harnesses"] = validate_agent_harnesses(data.get("supported_harnesses", []))
    if not isinstance(data.get("components", []), list):
        raise AgentDefinitionError("components", "Agent components must be a list.")
    return data


def build_agent_payload(definition: Mapping[str, Any], *, default_version: str = "1.0.0") -> dict[str, Any]:
    """Build the canonical wire payload used by ``agent publish``."""

    data = validate_agent_definition(definition, default_version=default_version)
    payload = {
        "name": data["name"],
        "version": data["version"],
        "description": data.get("description", ""),
        "category": data.get("category"),
        "owner": data.get("owner", ""),
        "model_name": data.get("model_name", "claude-sonnet-4"),
        "model_config_json": data.get("model_config_json", {}) or {},
        "models_by_harness": data.get("models_by_harness", {}) or {},
        "prompt": data.get("prompt", ""),
        "supported_harnesses": data.get("supported_harnesses", []),
        "mcp_server_ids": data.get("mcp_server_ids", []),
        "components": data.get("components", []),
        "external_mcps": data.get("external_mcps", []),
        "success_criteria": data.get("success_criteria"),
    }
    for field in ("visibility", "team_id"):
        if field in data:
            payload[field] = data[field]
    return payload


def _has_prompt_component(components: object) -> bool:
    return isinstance(components, list) and any(
        isinstance(component, Mapping) and component.get("component_type") == "prompt" for component in components
    )


def build_agent_draft_payload(definition: Mapping[str, Any], *, default_version: str = "1.0.0") -> dict[str, Any]:
    """Build and validate a payload for ``POST /api/v1/agents/draft``."""

    payload = build_agent_payload(definition, default_version=default_version)
    model_name = payload.get("model_name")
    if not isinstance(model_name, str) or not model_name.strip():
        raise AgentDefinitionError("model_name", "Agent model_name is required.")
    prompt = payload.get("prompt")
    if (not isinstance(prompt, str) or not prompt.strip()) and not _has_prompt_component(payload.get("components")):
        raise AgentDefinitionError(
            "prompt",
            "A system prompt is required. Either set a custom prompt or add a Prompt component.",
        )
    owner = payload.get("owner")
    if not isinstance(owner, str):
        raise AgentDefinitionError("owner", "Agent owner must be a string.")
    models_by_harness = payload.get("models_by_harness")
    if not isinstance(models_by_harness, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in models_by_harness.items()
    ):
        raise AgentDefinitionError("models_by_harness", "Agent models_by_harness must map harness names to models.")
    return payload


def create_agent_draft(definition: Mapping[str, Any]) -> dict:
    """Validate and create exactly one agent draft."""

    return client.post("/api/v1/agents/draft", build_agent_draft_payload(definition))


def _agent_evidence(candidate: DiscoveryCandidate) -> tuple[DiscoveredAgent, Sequence[DiscoveryEvidence]]:
    if candidate.component_type is not ComponentType.AGENT:
        raise AgentDefinitionError("component_type", "Discovery candidate is not an agent.")
    evidence = tuple(item for item in candidate.evidence if isinstance(item.component, DiscoveredAgent))
    if not evidence:
        raise AgentDefinitionError("evidence", "Agent discovery candidate has no agent definition evidence.")
    components = {
        (
            item.component.name,
            item.component.description,
            item.component.model_name,
            item.component.prompt,
        )
        for item in evidence
    }
    if len(components) != 1:
        raise AgentDefinitionError("evidence", "Agent discovery evidence is ambiguous.")
    return evidence[0].component, evidence


def agent_definition_from_candidate(
    candidate: DiscoveryCandidate,
    *,
    owner: str,
    version: str = "0.1.0",
) -> dict[str, Any]:
    """Convert one complete discovered agent into a validated in-memory definition."""

    component, evidence = _agent_evidence(candidate)
    if not isinstance(owner, str) or not owner.strip():
        raise AgentDefinitionError("owner", "Authenticated Registry owner is required.")
    if not component.model_name.strip():
        raise AgentDefinitionError("model_name", "Discovered agent model_name is required.")
    if not component.prompt.strip():
        raise AgentDefinitionError("prompt", "Discovered agent prompt is required.")
    try:
        name = slugify(component.name or candidate.local_name)
    except ValueError as error:
        raise AgentDefinitionError("name", "Discovered agent name cannot be converted to a valid slug.") from error
    harnesses = sorted({item.harness for item in evidence if item.harness})
    definition = {
        "name": name,
        "version": version,
        "description": component.description,
        "owner": owner.strip(),
        "model_name": component.model_name,
        "model_config_json": {},
        "models_by_harness": {},
        "prompt": component.prompt,
        "supported_harnesses": harnesses,
        "components": [],
        "external_mcps": [],
        "success_criteria": None,
    }
    return validate_agent_definition(definition, default_version="0.1.0")


def build_discovered_agent_draft_payload(
    candidate: DiscoveryCandidate,
    *,
    owner: str,
    version: str = "0.1.0",
) -> dict[str, Any]:
    """Convert discovery evidence through the normal agent payload builder."""

    definition = agent_definition_from_candidate(candidate, owner=owner, version=version)
    return build_agent_draft_payload(definition, default_version="0.1.0")
