# SPDX-License-Identifier: Apache-2.0
"""Review checks (deterministic snapshot checks and live pin readiness)."""

import json
import re

from sqlalchemy import select

from models.agent_component import AgentComponent
from models.mcp import ListingStatus
from services.agent_lock import VERSION_MODELS

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
    if subject_type == "mcp":
        checks.append(
            {
                "id": "mcp_validation",
                "name": "MCP validation",
                "status": "pass" if version.mcp_validated else "fail",
                "required": True,
                "details": [] if version.mcp_validated else ["Validation has not passed"],
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
    if base_files:
        from services.review.diff import diff_files

        sensitive = ("auto_approve", "tool_filter", "scope", "network_policy", "slash_command")
        changed = [
            d["path"]
            for d in diff_files(base_files, files)
            if d["status"] != "unchanged"
            and any(
                s in (base_files.get(d["path"], {}).get("content", "") + files.get(d["path"], {}).get("content", ""))
                for s in sensitive
            )
        ]
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


async def pinned_component_blockers(db, version_id) -> list[dict]:
    rows = (
        (await db.execute(select(AgentComponent).where(AgentComponent.agent_version_id == version_id))).scalars().all()
    )
    blockers = []
    for row in rows:
        model = VERSION_MODELS.get(row.component_type)
        version = await db.get(model, row.resolved_version_id) if model and row.resolved_version_id else None
        if (
            not version
            or version.listing_id != row.component_id
            or version.status not in (ListingStatus.approved, ListingStatus.archived)
        ):
            blockers.append({"type": row.component_type, "id": str(row.component_id), "version": row.resolved_version})
    return blockers
