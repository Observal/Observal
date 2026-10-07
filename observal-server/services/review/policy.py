# SPDX-License-Identifier: Apache-2.0
"""Organization-wide policy, with teamspace overrides for private/public subjects."""

import json
from dataclasses import dataclass, field

import services.dynamic_settings as ds

SUBJECT_TYPES = ("agent", "mcp", "skill", "hook", "prompt", "sandbox")


@dataclass(frozen=True)
class ApprovalPolicy:
    required_approvals: dict[str, int] = field(default_factory=lambda: dict.fromkeys(SUBJECT_TYPES, 1))
    self_approval: str = "not_counted"
    dismiss_stale_approvals: bool = True
    require_resolved_threads: bool = False
    auto_publish: bool = False
    source: str = "organization"


def parse_policy(raw: str | dict | None, *, source="organization") -> ApprovalPolicy:
    data = json.loads(raw) if isinstance(raw, str) and raw else (raw or {})
    if not isinstance(data, dict):
        raise ValueError("Review policy must be an object")
    counts = dict.fromkeys(SUBJECT_TYPES, 1)
    for key, value in data.get("required_approvals", {}).items():
        if key not in counts or type(value) is not int or not 1 <= value <= 5:
            raise ValueError("Approval counts must be 1-5 for a known subject type")
        counts[key] = value
    if data.get("self_approval", "not_counted") not in ("not_counted", "counted"):
        raise ValueError("Invalid self-approval policy")
    flags = ("dismiss_stale_approvals", "require_resolved_threads", "auto_publish")
    if any(type(data.get(key, False)) is not bool for key in flags):
        raise ValueError("Review policy flags must be booleans")
    return ApprovalPolicy(
        counts,
        data.get("self_approval", "not_counted"),
        data.get("dismiss_stale_approvals", True),
        data.get("require_resolved_threads", False),
        data.get("auto_publish", False),
        source,
    )


async def policy_for(review) -> ApprovalPolicy:
    org = parse_policy(await ds.get("review.policy", default="{}"))
    if not review.team_id:
        return org
    raw = await ds.get(f"review.policy.team.{review.team_id}", default="")
    if not raw:
        return org
    team = parse_policy(raw, source="teamspace")
    if review.is_private:
        return team
    return ApprovalPolicy(
        {key: max(org.required_approvals[key], team.required_approvals[key]) for key in SUBJECT_TYPES},
        "not_counted" if org.self_approval == "not_counted" else team.self_approval,
        org.dismiss_stale_approvals or team.dismiss_stale_approvals,
        org.require_resolved_threads or team.require_resolved_threads,
        org.auto_publish and team.auto_publish,
        "organization + teamspace",
    )
