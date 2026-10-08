# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Review checks (deterministic snapshot checks and live pin readiness)."""

import json
import re

import yaml
from sqlalchemy import select

from models.agent_component import AgentComponent
from services.agent_lock import pinned_component_blockers as legacy_pinned_component_blockers

CREDENTIAL = re.compile(r"(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16})")


def snapshot_checks(files: dict, version=None, *, subject_type=None, base_files=None) -> list[dict]:
    leaked = [path for path, file in files.items() if CREDENTIAL.search(file["content"])]
    if version is not None:
        for column in version.__table__.columns:
            value = getattr(version, column.name)
            if isinstance(value, (str, dict, list)) and CREDENTIAL.search(
                value if isinstance(value, str) else json.dumps(value)
            ):
                leaked.append(column.name)
    checks = [
        {
            "id": "secrets",
            "name": "Secret scan",
            "status": "fail" if leaked else "pass",
            "required": True,
            "details": leaked,
        }
    ]
    if version is None or subject_type is None:
        return checks
    required = {
        "agent": ("description", "prompt", "model_name"),
        "mcp": ("description",),
        "skill": ("description", "task_type"),
        "hook": ("description", "event", "handler_type"),
        "prompt": ("description", "template"),
        "sandbox": ("description", "runtime_type", "image"),
    }
    missing = [name for name in required[subject_type] if not getattr(version, name, None)]
    if subject_type == "mcp" and not (version.command or version.url or version.docker_image):
        missing.append("command/url/docker_image")
    checks.append(
        {
            "id": "schema",
            "name": "Required fields",
            "status": "fail" if missing else "pass",
            "required": True,
            "details": missing,
        }
    )
    if subject_type == "agent" and version.gaming_flags:
        checks.append(
            {
                "id": "prompt_safety",
                "name": "Prompt safety",
                "status": "warn",
                "required": False,
                "details": ["Review anti-gaming flags"],
            }
        )
    source = getattr(version, "source_url", None) or getattr(version, "git_url", None)
    if source:
        checks.append(
            {
                "id": "provenance",
                "name": "Source provenance",
                "status": "pass" if getattr(version, "resolved_sha", None) else "warn",
                "required": False,
                "details": [] if getattr(version, "resolved_sha", None) else ["No resolved SHA"],
            }
        )
    changed = permission_delta(base_files or {}, files)
    if changed:
        checks.append(
            {
                "id": "permission_delta",
                "name": "Permission delta",
                "status": "warn",
                "required": False,
                "details": changed,
            }
        )
    return checks


_SENSITIVE_FIELDS = ("auto_approve", "tool_filter", "scope", "network_policy", "slash_command")


def _manifest_values(file: dict | None) -> dict:
    try:
        data = yaml.safe_load((file or {}).get("content") or "") or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def permission_delta(base_files: dict, files: dict) -> list[str]:
    """Sensitive manifest fields whose value differs from the review base."""
    changed = []
    for path in sorted(base_files.keys() | files.keys()):
        if not path.endswith(".yaml") or path == "components.yaml":
            continue
        before, after = _manifest_values(base_files.get(path)), _manifest_values(files.get(path))
        changed.extend(
            f"{path}:{field}"
            for field in _SENSITIVE_FIELDS
            if (field in before or field in after) and before.get(field) != after.get(field)
        )
    return changed


async def pinned_component_blockers(db, version_id) -> list[dict]:
    """Same pin resolution the legacy review gate uses, including unlocked legacy pins."""
    rows = (
        (await db.execute(select(AgentComponent).where(AgentComponent.agent_version_id == version_id))).scalars().all()
    )
    return await legacy_pinned_component_blockers(db, rows)
