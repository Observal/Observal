# SPDX-License-Identifier: Apache-2.0
"""Review checks (deterministic snapshot checks and live pin readiness)."""

import json
import re

from sqlalchemy import select

from models.agent_component import AgentComponent
from models.mcp import ListingStatus
from services.agent_lock import VERSION_MODELS

CREDENTIAL = re.compile(r"(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16})")


def snapshot_checks(files: dict, version=None) -> list[dict]:
    leaked = [path for path, file in files.items() if CREDENTIAL.search(file["content"])]
    if version is not None:
        for column in version.__table__.columns:
            value = getattr(version, column.name)
            if isinstance(value, (str, dict, list)) and CREDENTIAL.search(
                value if isinstance(value, str) else json.dumps(value)
            ):
                leaked.append(column.name)
    return [
        {
            "id": "secrets",
            "name": "Secret scan",
            "status": "fail" if leaked else "pass",
            "required": True,
            "details": leaked,
        }
    ]


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
