# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Side-effect-free portable draft readiness and payload construction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from observal_cli.agent_drafts import AgentDefinitionError, build_discovered_agent_draft_payload
from observal_cli.component_drafts import (
    DraftPayloadError,
    build_hook_draft_payload,
    build_mcp_draft_payload,
    build_skill_draft_payload,
)
from observal_cli.constants import VALID_HOOK_EVENTS, VALID_HOOK_HANDLER_TYPES
from observal_cli.discovery.models import (
    ComponentType,
    DiscoveryCandidate,
    DiscoveryEvidence,
    LaunchKind,
    ReasonCode,
    RegistrationStatus,
    SupportStatus,
)
from observal_cli.discovery.providers._utils import MAX_METADATA_FILE_BYTES
from observal_cli.discovery.redact import redact_text, redact_value, sanitize_url
from observal_cli.harness import DiscoveredAgent, DiscoveredHook, DiscoveredMcp, DiscoveredSkill
from observal_shared.registry_slug import slugify


class RegistrationPayloadError(ValueError):
    """Discovery evidence cannot produce a portable draft payload."""

    def __init__(
        self,
        message: str,
        *,
        field: str = "draft_payload",
        unsupported: bool = False,
        missing: bool = True,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.unsupported = unsupported
        self.missing = missing


@dataclass(frozen=True)
class ReadinessValidation:
    """Portable draft readiness without prompting or network mutation."""

    support_status: SupportStatus
    registration_status: RegistrationStatus
    reason_codes: tuple[ReasonCode, ...] = ()
    missing_fields: tuple[str, ...] = ()
    message: str | None = None


def _component_evidence(candidate: DiscoveryCandidate, expected_type: type) -> DiscoveryEvidence:
    evidence = [item for item in candidate.evidence if isinstance(item.component, expected_type)]
    if not evidence:
        raise RegistrationPayloadError(
            f"No {candidate.component_type or 'component'} definition evidence is available",
            field="definition_evidence",
        )
    return evidence[0]


def _harnesses(candidate: DiscoveryCandidate) -> list[str]:
    return sorted({item.harness for item in candidate.evidence if item.harness})


def _base_payload(candidate: DiscoveryCandidate, owner: str, component: object) -> dict[str, Any]:
    name = getattr(component, "name", candidate.local_name)
    description = getattr(component, "description", "")
    try:
        canonical_name = slugify(name or candidate.local_name)
    except ValueError as error:
        raise RegistrationPayloadError(
            "The discovered name cannot be converted to a valid Registry slug", field="name"
        ) from error
    return {
        "name": canonical_name,
        "version": "0.1.0",
        "description": description if isinstance(description, str) else "",
        "owner": owner,
        "supported_harnesses": _harnesses(candidate),
    }


def _mcp_payload(candidate: DiscoveryCandidate, owner: str) -> dict[str, Any]:
    evidence = _component_evidence(candidate, DiscoveredMcp)
    component = evidence.component
    assert isinstance(component, DiscoveredMcp)
    launch = evidence.launch
    if launch is None or candidate.launch_fingerprint is None:
        raise RegistrationPayloadError(
            "MCP discovery evidence has no portable structured launch",
            field="portable_launch",
            unsupported=True,
        )
    try:
        kind = LaunchKind(launch.kind)
    except ValueError as error:
        raise RegistrationPayloadError(
            "MCP launch type is unsupported for portable registration",
            field="portable_launch",
            unsupported=True,
            missing=False,
        ) from error
    payload = _base_payload(candidate, owner, component)
    payload.update(
        {
            "category": "other",
            "environment_variables": [
                {"name": name, "description": "", "required": True} for name in launch.environment_names
            ],
            "headers": [{"name": name, "description": "", "required": True} for name in launch.header_names] or None,
        }
    )
    if launch.transport:
        payload["transport"] = launch.transport
    if kind is LaunchKind.URL:
        url = sanitize_url(launch.url or "")
        if not url:
            raise RegistrationPayloadError("MCP URL is not portable", field="url", unsupported=True, missing=False)
        payload["url"] = url
    elif kind is LaunchKind.NPM:
        requirement = launch.requirement or launch.package
        if not requirement:
            raise RegistrationPayloadError("MCP npm package is missing", field="package")
        payload["command"] = "npx"
        payload["args"] = ["-y", requirement, *launch.arguments]
    elif kind in {LaunchKind.UV, LaunchKind.PIPX}:
        requirement = launch.requirement or launch.package
        if not requirement:
            raise RegistrationPayloadError("MCP Python package is missing", field="package")
        if kind is LaunchKind.PIPX and launch.version and launch.requirement is None:
            requirement = f"{requirement}=={launch.version}"
        payload["command"] = "uvx"
        payload["args"] = [requirement, *launch.arguments]
    else:
        raise RegistrationPayloadError(
            "MCP launch depends on a non-portable local executable or file",
            field="portable_launch",
            unsupported=True,
            missing=False,
        )
    return payload


def _skill_payload(candidate: DiscoveryCandidate, owner: str) -> dict[str, Any]:
    evidence = _component_evidence(candidate, DiscoveredSkill)
    component = evidence.component
    assert isinstance(component, DiscoveredSkill)
    source_path = evidence.source_path
    if source_path is None:
        raise RegistrationPayloadError("Skill source content is unavailable", field="skill_md_content")
    path = Path(source_path)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_METADATA_FILE_BYTES:
            raise RegistrationPayloadError(
                "Skill source must be a readable SKILL.md within the discovery size limit",
                field="skill_md_content",
            )
        with path.open("rb") as source:
            raw_content = source.read(MAX_METADATA_FILE_BYTES + 1)
        if len(raw_content) > MAX_METADATA_FILE_BYTES:
            raise RegistrationPayloadError("Skill source exceeds the discovery size limit", field="skill_md_content")
        content = raw_content.decode("utf-8", errors="replace")
    except OSError as error:
        raise RegistrationPayloadError("Skill source could not be read", field="skill_md_content") from error
    if not content.strip():
        raise RegistrationPayloadError("Skill source is empty", field="skill_md_content")
    payload = _base_payload(candidate, owner, component)
    payload.update(
        {
            "skill_path": "/",
            "skill_md_content": redact_text(content),
            "delivery_mode": "registry_direct",
            "target_agents": [],
            "task_type": component.task_type or "general",
        }
    )
    return payload


def _portable_hook_config(component: DiscoveredHook) -> dict[str, Any]:
    if component.event not in VALID_HOOK_EVENTS:
        raise RegistrationPayloadError(
            "Hook event is not supported by the Registry", field="event", unsupported=True, missing=False
        )
    if component.handler_type not in VALID_HOOK_HANDLER_TYPES:
        raise RegistrationPayloadError(
            "Hook handler type is not portable", field="handler_type", unsupported=True, missing=False
        )
    config = redact_value(component.handler_config)
    if not isinstance(config, dict) or not config:
        raise RegistrationPayloadError("Hook handler configuration is missing", field="handler_config")
    if component.handler_type == "http":
        url = config.get("url")
        safe_url = sanitize_url(url) if isinstance(url, str) else None
        if not safe_url:
            raise RegistrationPayloadError("Hook HTTP handler has no portable URL", field="handler_config.url")
        config["url"] = safe_url
    else:
        command = config.get("command")
        if not isinstance(command, str) or not command.strip():
            raise RegistrationPayloadError("Hook command handler has no command", field="handler_config.command")
        if any(character.isspace() for character in command.strip()):
            raise RegistrationPayloadError(
                "Hook command must use a structured executable and argument list",
                field="handler_config.command",
                unsupported=True,
                missing=False,
            )
        arguments = config.get("args", [])
        if not isinstance(arguments, list) or any(not isinstance(argument, str) for argument in arguments):
            raise RegistrationPayloadError(
                "Hook command arguments must be a list of strings", field="handler_config.args"
            )
        command_path = Path(command).expanduser()
        if command_path.is_absolute() or "/" in command or "\\" in command:
            raise RegistrationPayloadError(
                "Hook command depends on a local executable path",
                field="handler_config.command",
                unsupported=True,
                missing=False,
            )
    return config


def _hook_payload(candidate: DiscoveryCandidate, owner: str) -> dict[str, Any]:
    evidence = _component_evidence(candidate, DiscoveredHook)
    component = evidence.component
    assert isinstance(component, DiscoveredHook)
    payload = _base_payload(candidate, owner, component)
    payload.update(
        {
            "event": component.event,
            "execution_mode": "async",
            "priority": 100,
            "handler_type": component.handler_type,
            "handler_config": _portable_hook_config(component),
            "scope": "agent",
        }
    )
    return payload


def build_discovery_draft_payload(candidate: DiscoveryCandidate, *, owner: str) -> dict[str, Any]:
    """Build and validate a portable payload without prompting or mutation."""

    if candidate.component_type is ComponentType.AGENT:
        return build_discovered_agent_draft_payload(candidate, owner=owner)
    if candidate.component_type is ComponentType.MCP:
        return build_mcp_draft_payload(_mcp_payload(candidate, owner))
    if candidate.component_type is ComponentType.SKILL:
        return build_skill_draft_payload(_skill_payload(candidate, owner))
    if candidate.component_type is ComponentType.HOOK:
        return build_hook_draft_payload(_hook_payload(candidate, owner))
    raise RegistrationPayloadError("Candidate type is not registrable", field="component_type", unsupported=True)


def validate_candidate_readiness(candidate: DiscoveryCandidate) -> ReadinessValidation:
    """Return exact portable-draft readiness without network or user interaction."""

    if candidate.component_type is None:
        return ReadinessValidation(
            SupportStatus.UNSUPPORTED,
            RegistrationStatus.NOT_APPLICABLE,
            (ReasonCode.PACKAGE_EVIDENCE_ONLY,),
        )

    component = next((item.component for item in candidate.evidence if item.component is not None), None)
    if isinstance(component, DiscoveredAgent):
        missing = tuple(
            field for field, value in (("model_name", component.model_name), ("prompt", component.prompt)) if not value
        )
        if missing:
            return ReadinessValidation(
                SupportStatus.SUPPORTED,
                RegistrationStatus.INCOMPLETE,
                (ReasonCode.MISSING_REQUIRED_FIELDS,),
                missing,
            )

    try:
        build_discovery_draft_payload(candidate, owner="discovery")
    except AgentDefinitionError as error:
        return ReadinessValidation(
            SupportStatus.SUPPORTED,
            RegistrationStatus.INCOMPLETE,
            (ReasonCode.MISSING_REQUIRED_FIELDS,),
            (error.field,),
            str(error),
        )
    except RegistrationPayloadError as error:
        reasons = [ReasonCode.UNSUPPORTED_LAUNCH if error.unsupported else ReasonCode.MISSING_REQUIRED_FIELDS]
        if error.unsupported and error.missing:
            reasons.append(ReasonCode.MISSING_REQUIRED_FIELDS)
        return ReadinessValidation(
            SupportStatus.UNSUPPORTED if error.unsupported else SupportStatus.SUPPORTED,
            RegistrationStatus.INCOMPLETE,
            tuple(reasons),
            (error.field,),
            str(error),
        )
    except (DraftPayloadError, OSError) as error:
        return ReadinessValidation(
            SupportStatus.SUPPORTED,
            RegistrationStatus.INCOMPLETE,
            (ReasonCode.MISSING_REQUIRED_FIELDS,),
            ("draft_payload",),
            str(error),
        )
    return ReadinessValidation(SupportStatus.SUPPORTED, RegistrationStatus.ELIGIBLE)
