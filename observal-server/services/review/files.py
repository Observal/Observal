# SPDX-License-Identifier: Apache-2.0
"""Canonical, secret-redacted virtual file trees for review snapshots."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

import yaml
from sqlalchemy import select

from models.agent_component import AgentComponent
from services.agent_lock import LISTING_MODELS, VERSION_MODELS
from services.review.checks import CREDENTIAL

SECRET = re.compile(r"secret|token|key|password|credential|authorization", re.I)
FIELDS = {
    "skill": (
        "task_type",
        "slash_command",
        "triggers",
        "target_agents",
        "activation_keywords",
        "supported_harnesses",
        "delivery_mode",
        "skill_path",
        "git_url",
        "git_ref",
        "mcp_server_config",
        "is_power",
        "has_scripts",
        "has_templates",
    ),
    "prompt": ("category", "variables", "model_hints", "tags", "supported_harnesses"),
    "hook": (
        "event",
        "execution_mode",
        "priority",
        "handler_type",
        "handler_config",
        "scope",
        "tool_filter",
        "file_pattern",
        "requirements",
        "source_url",
        "source_ref",
        "source_path",
        "resolved_sha",
    ),
    "mcp": (
        "transport",
        "framework",
        "command",
        "args",
        "url",
        "headers",
        "docker_image",
        "environment_variables",
        "auto_approve",
        "supported_harnesses",
        "source_url",
        "source_ref",
        "resolved_sha",
    ),
    "sandbox": (
        "runtime_type",
        "image",
        "dockerfile_url",
        "resource_limits",
        "network_policy",
        "allowed_mounts",
        "env_vars",
        "entrypoint",
        "runtime_config",
        "sandbox_path",
        "source_url",
        "source_ref",
        "resolved_sha",
    ),
    "agent": (
        "description",
        "model_name",
        "models_by_harness",
        "model_config_json",
        "supported_harnesses",
        "required_capabilities",
        "external_mcps",
        "success_criteria",
    ),
}


def redact(value, *, key=""):
    """Fail closed for credential-named keys, including nested config overrides."""
    if key == "headers" and isinstance(value, dict):
        return {str(k): "<redacted>" for k in value}
    if key == "value" or SECRET.search(key):
        return "<redacted>" if value is not None else None
    if isinstance(value, dict):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _file(content, lang, *, pinned=False, generated=False):
    content = CREDENTIAL.sub("<redacted>", content or "")
    return {
        "content": content.rstrip("\n") + "\n" if content else "",
        "lang": lang,
        "pinned": pinned,
        "generated": generated,
    }


def _manifest(ver, fields):
    return {field: redact(getattr(ver, field), key=field) for field in fields if hasattr(ver, field)}


def _safe_name(name: str | None, fallback: str) -> str:
    path = PurePosixPath(name or "")
    if path.is_absolute() or ".." in path.parts or not path.name or name != path.name:
        return fallback
    return path.name


def render_component(subject_type: str, ver, *, pinned=False) -> dict:
    """Stored content only; never fetch a git URL while rendering a review."""
    if subject_type not in VERSION_MODELS:
        raise ValueError(f"Unknown review subject type: {subject_type}")
    files = {
        f"{subject_type}.yaml": _file(
            yaml.safe_dump(_manifest(ver, FIELDS[subject_type]), sort_keys=False, allow_unicode=True),
            "yaml",
            pinned=pinned,
        )
    }
    if subject_type == "skill":
        files["SKILL.md"] = _file(ver.skill_md_content, "markdown", pinned=pinned)
        if ver.script_content:
            filename = _safe_name(ver.script_filename, "script.sh")
            files[f"scripts/{filename}"] = _file(ver.script_content, filename.rsplit(".", 1)[-1], pinned=pinned)
    elif subject_type == "prompt":
        files["PROMPT.md"] = _file(ver.template, "markdown", pinned=pinned)
    elif subject_type == "hook" and ver.script_content:
        filename = _safe_name(ver.script_filename, "hook.sh")
        files[filename] = _file(ver.script_content, filename.rsplit(".", 1)[-1], pinned=pinned)
    elif subject_type == "mcp":
        if ver.tools_schema:
            files["tools.json"] = _file(
                json.dumps(redact(ver.tools_schema), indent=2, sort_keys=True), "json", pinned=pinned
            )
        if ver.setup_instructions:
            files["SETUP.md"] = _file(ver.setup_instructions, "markdown", pinned=pinned)
    return dict(sorted(files.items()))


async def render_files(subject_type: str, ver, db) -> dict:
    if subject_type != "agent":
        return render_component(subject_type, ver)
    files = {
        "agent.yaml": _file(
            yaml.safe_dump(_manifest(ver, FIELDS["agent"]), sort_keys=False, allow_unicode=True), "yaml"
        ),
        "prompt.md": _file(ver.prompt, "markdown"),
    }
    rows = (
        (
            await db.execute(
                select(AgentComponent)
                .where(AgentComponent.agent_version_id == ver.id)
                .order_by(AgentComponent.order_index)
            )
        )
        .scalars()
        .all()
    )
    pins = []
    for comp in rows:
        entry = {
            "type": comp.component_type,
            "id": str(comp.component_id),
            "version": comp.resolved_version,
            "config_override": redact(comp.config_override),
        }
        listing_model = LISTING_MODELS.get(comp.component_type)
        version_model = VERSION_MODELS.get(comp.component_type)
        listing = await db.get(listing_model, comp.component_id) if listing_model else None
        if listing:
            entry["name"] = f"{listing.namespace}/{listing.slug}"
        # The id is stable and cannot be a path traversal; use it rather than the untrusted name.
        if version_model and comp.resolved_version_id:
            pinned = await db.get(version_model, comp.resolved_version_id)
            if pinned and pinned.listing_id == comp.component_id:
                for path, file in render_component(comp.component_type, pinned, pinned=True).items():
                    files[f"components/{comp.component_type}/{comp.component_id!s}/{path}"] = file
        pins.append(entry)
    files["components.yaml"] = _file(yaml.safe_dump(pins, sort_keys=False, allow_unicode=True), "yaml")
    for harness, config in sorted((ver.harness_configs or {}).items()):
        files[f"harness/{_safe_name(harness, 'unknown')}.json"] = _file(
            json.dumps(redact(config), indent=2, sort_keys=True), "json", generated=True
        )
    return dict(sorted(files.items()))
