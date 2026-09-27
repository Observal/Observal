# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi
# SPDX-License-Identifier: Apache-2.0

"""Project bounded registry pin claims into stable per-component occurrences."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass

SUPPORTED_TYPES = frozenset({"mcp", "skill", "hook"})


@dataclass(frozen=True)
class Occurrence:
    occurrence_key: str
    component_type: str
    source: str
    harness: str
    scope: str
    parent_agent_id: str
    parent_agent_version: str
    raw_listing_id: str
    raw_name: str
    raw_version: str
    qualified_name: str
    local_name: str
    verification_status: str


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def normalize_snapshot(pinned_versions: object, drift: object) -> list[Occurrence]:
    """Never inspect file contents; legacy pin claims remain diagnostic only."""
    if not isinstance(pinned_versions, dict):
        return []
    drift = drift if isinstance(drift, dict) else {}
    is_v2 = pinned_versions.get("schema_version") == 2
    globally_drifted = drift.get("is_canonical") is False
    verifications = drift.get("mcp_verifications")
    verifications = verifications if isinstance(verifications, list) else []
    records: list[dict[str, str]] = []

    def append(
        pin: object, *, source: str, harness: str, scope: str, parent_id: str = "", parent_version: str = ""
    ) -> None:
        if not isinstance(pin, dict) or pin.get("type") not in SUPPORTED_TYPES:
            return
        kind = pin["type"]
        alias = _text(pin.get("local_name"))
        raw_id = _text(pin.get("id"))
        item_scope = _text(pin.get("scope")) or scope
        verification = "unverified"
        if kind == "mcp":
            for item in verifications:
                if not isinstance(item, dict):
                    continue
                if all(
                    item.get(key) == value
                    for key, value in (
                        ("harness", harness),
                        ("component_id", raw_id),
                        ("alias", alias),
                        ("scope", item_scope),
                        ("parent_agent_id", parent_id),
                    )
                ):
                    status = item.get("status")
                    verification = (
                        "verified"
                        if is_v2 and not globally_drifted and raw_id and alias and status == "verified"
                        else (
                            "drifted"
                            if status in {"drifted", "missing"} or drift.get("is_canonical") is False
                            else "unverified"
                        )
                    )
                    break
        records.append(
            {
                "component_type": kind,
                "source": source,
                "harness": harness,
                "scope": item_scope,
                "parent_agent_id": parent_id,
                "parent_agent_version": parent_version,
                "raw_listing_id": raw_id,
                "raw_name": _text(pin.get("name")),
                "raw_version": _text(pin.get("version")),
                "qualified_name": _text(pin.get("qualified_name")),
                "local_name": alias,
                "verification_status": verification,
            }
        )

    agents = pinned_versions.get("agents")
    for agent in agents[:128] if isinstance(agents, list) else []:
        if not isinstance(agent, dict):
            continue
        harness = _text(agent.get("harness"))
        scope = _text(agent.get("scope")) or "project"
        components = agent.get("components")
        for pin in components[:128] if isinstance(components, list) else []:
            append(
                pin,
                source="agent",
                harness=harness,
                scope=scope,
                parent_id=_text(agent.get("id")),
                parent_version=_text(agent.get("version")),
            )
    standalone = pinned_versions.get("standalone")
    for pin in standalone[:512] if isinstance(standalone, list) else []:
        if isinstance(pin, dict):
            append(pin, source="standalone", harness=_text(pin.get("harness")), scope="project")

    # One installed alias cannot prove two different registry identities in the
    # same harness and scope. A duplicated claim about the *same* identity is fine.
    alias_claims: dict[tuple[str, str, str], set[tuple[str, str]]] = defaultdict(set)
    for record in records:
        if record["component_type"] == "mcp" and record["local_name"]:
            alias_claims[record["harness"], record["scope"], record["local_name"]].add(
                (record["raw_listing_id"], record["raw_version"])
            )
    for record in records:
        if (
            record["component_type"] == "mcp"
            and len(alias_claims.get((record["harness"], record["scope"], record["local_name"]), ())) > 1
        ):
            record["verification_status"] = "unverified"

    # Duplicate identical occurrences need distinct keys; sorting and assigning
    # ordinals by immutable content keeps keys stable even if lockfile order changes.
    counters: dict[str, int] = defaultdict(int)
    occurrences: list[Occurrence] = []
    for record in sorted(records, key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False)):
        digest = hashlib.sha256(
            json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        index = counters[digest]
        counters[digest] += 1
        occurrences.append(Occurrence(occurrence_key=f"{digest[:32]}-{index:04d}", **record))
    return occurrences


def occurrence_row(occurrence: Occurrence) -> dict[str, str]:
    return asdict(occurrence)
