# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-FileCopyrightText: 2026 VishnuM049 <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Reusable payload validation and mutation services for component drafts.

The builders intentionally preserve the caller's payload shape after validation.
Existing CLI submit commands therefore keep their wire contracts, while discovery
can use the same boundary before performing a draft mutation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING
from uuid import UUID

from observal_cli import client
from observal_cli.constants import VALID_HARNESSES, VALID_MCP_TRANSPORTS

if TYPE_CHECKING:
    from typing import Any


_SLASH_COMMAND_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class DraftPayloadError(ValueError):
    """A component payload does not satisfy its draft request contract."""


def _payload_copy(payload: Mapping[str, Any], component: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise DraftPayloadError(f"{component} draft payload must be an object")
    copied = deepcopy(dict(payload))
    name = copied.get("name")
    if not isinstance(name, str):
        raise DraftPayloadError(f"{component} draft field 'name' must be a string")
    return copied


def _text(payload: Mapping[str, Any], component: str, *fields: str) -> None:
    for field in fields:
        if field in payload and not isinstance(payload[field], str):
            raise DraftPayloadError(f"{component} draft field '{field}' must be a string")


def _optional_text(payload: Mapping[str, Any], component: str, *fields: str) -> None:
    for field in fields:
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise DraftPayloadError(f"{component} draft field '{field}' must be a string or null")


def _string_list(payload: Mapping[str, Any], component: str, *fields: str, nullable: bool = False) -> None:
    for field in fields:
        if field not in payload:
            continue
        value = payload[field]
        if nullable and value is None:
            continue
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise DraftPayloadError(f"{component} draft field '{field}' must be a list of strings")


def _validate_common(payload: Mapping[str, Any], component: str) -> None:
    _text(payload, component, "version", "description", "owner")
    visibility = payload.get("visibility", "public")
    if visibility not in {"public", "team"}:
        raise DraftPayloadError(f"{component} draft field 'visibility' must be public or team")
    team_id = payload.get("team_id")
    if team_id is not None:
        try:
            UUID(str(team_id))
        except (TypeError, ValueError) as error:
            raise DraftPayloadError(f"{component} draft field 'team_id' must be a UUID or null") from error
    _string_list(payload, component, "supported_harnesses")
    unsupported = [item for item in payload.get("supported_harnesses") or [] if item not in VALID_HARNESSES]
    if unsupported:
        raise DraftPayloadError(f"{component} draft field 'supported_harnesses' contains an unknown harness")


def _named_objects(
    payload: Mapping[str, Any],
    component: str,
    field: str,
    *,
    nullable: bool = False,
    allowed_keys: frozenset[str] | None = None,
) -> None:
    if field not in payload:
        return
    values = payload[field]
    if nullable and values is None:
        return
    if not isinstance(values, list):
        raise DraftPayloadError(f"{component} draft field '{field}' must be a list")
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("name"), str):
            raise DraftPayloadError(f"{component} draft field '{field}' contains an invalid entry")
        if allowed_keys is not None and set(value) - allowed_keys:
            raise DraftPayloadError(f"{component} draft field '{field}' contains unsupported fields")
        description = value.get("description")
        required = value.get("required")
        if description is not None and not isinstance(description, str):
            raise DraftPayloadError(f"{component} draft field '{field}' contains an invalid description")
        if required is not None and not isinstance(required, bool):
            raise DraftPayloadError(f"{component} draft field '{field}' contains an invalid required flag")


def build_mcp_draft_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy a payload compatible with ``McpDraftRequest``."""

    built = _payload_copy(payload, "MCP")
    _validate_common(built, "MCP")
    _text(built, "MCP", "category")
    _optional_text(
        built,
        "MCP",
        "git_url",
        "framework",
        "docker_image",
        "command",
        "url",
        "transport",
        "setup_instructions",
        "changelog",
    )
    transport = built.get("transport")
    if transport == "http":
        transport = "streamable-http"
        built["transport"] = transport
    if transport is not None and transport not in VALID_MCP_TRANSPORTS:
        raise DraftPayloadError(f"MCP draft field 'transport' must be one of: {', '.join(VALID_MCP_TRANSPORTS)}")
    has_process = bool(built.get("command") or built.get("docker_image"))
    has_remote = bool(built.get("url"))
    if has_process and has_remote:
        raise DraftPayloadError("MCP draft cannot define both process and remote URL fields")
    if transport == "stdio" and has_remote:
        raise DraftPayloadError("MCP draft stdio transport forbids URL")
    if transport in {"sse", "streamable-http"} and has_process:
        raise DraftPayloadError(f"MCP draft {transport} transport forbids process launch fields")
    _string_list(built, "MCP", "args", "auto_approve", nullable=True)
    _named_objects(
        built,
        "MCP",
        "headers",
        nullable=True,
        allowed_keys=frozenset({"name", "description", "required"}),
    )
    _named_objects(built, "MCP", "environment_variables")
    client_analysis = built.get("client_analysis")
    if client_analysis is not None and not isinstance(client_analysis, dict):
        raise DraftPayloadError("MCP draft field 'client_analysis' must be an object or null")
    return built


def build_skill_draft_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy a payload compatible with ``SkillDraftRequest``."""

    built = _payload_copy(payload, "skill")
    _validate_common(built, "skill")
    _text(built, "skill", "skill_path", "delivery_mode", "task_type")
    _optional_text(
        built,
        "skill",
        "git_url",
        "git_ref",
        "skill_md_content",
        "script_content",
        "script_filename",
        "slash_command",
    )
    _string_list(built, "skill", "target_agents")
    slash_command = built.get("slash_command")
    if slash_command:
        normalized_command = slash_command[1:] if slash_command.startswith("/") else slash_command
        if not _SLASH_COMMAND_RE.fullmatch(normalized_command):
            raise DraftPayloadError("skill draft field 'slash_command' has an invalid format")
    return built


def build_hook_draft_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy a payload compatible with ``HookDraftRequest``."""

    built = _payload_copy(payload, "hook")
    _validate_common(built, "hook")
    _text(built, "hook", "event", "execution_mode", "handler_type", "scope")
    _optional_text(
        built,
        "hook",
        "script_content",
        "script_filename",
        "source_url",
        "source_ref",
        "source_path",
    )
    _string_list(built, "hook", "tool_filter", "requirements", nullable=True)
    handler_config = built.get("handler_config", {})
    if not isinstance(handler_config, dict):
        raise DraftPayloadError("hook draft field 'handler_config' must be an object")
    priority = built.get("priority")
    if priority is not None and (not isinstance(priority, int) or isinstance(priority, bool)):
        raise DraftPayloadError("hook draft field 'priority' must be an integer")
    return built


def create_mcp_draft(payload: Mapping[str, Any]) -> dict:
    """Create one MCP draft through the canonical endpoint."""

    return client.post("/api/v1/mcps/draft", build_mcp_draft_payload(payload))


def create_skill_draft(payload: Mapping[str, Any]) -> dict:
    """Create one skill draft through the canonical endpoint."""

    return client.post("/api/v1/skills/draft", build_skill_draft_payload(payload))


def create_hook_draft(payload: Mapping[str, Any]) -> dict:
    """Create one hook draft through the canonical endpoint."""

    return client.post("/api/v1/hooks/draft", build_hook_draft_payload(payload))
