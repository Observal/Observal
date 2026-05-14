# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Cross-session contamination detection.

Session A's failure pattern produces session B's wrong approach when
they share user, retrieval cache key, or tool state. Pure: takes a
list of SessionRecord and emits CROSS_SESSION_CONTAMINATION
CheckResults for any A→B link found.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from services.eval.check_result.models import (
    Category,
    CheckResult,
    CheckType,
    SpanRef,
    Status,
)

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    user_id: str
    started_at: datetime
    failed: bool
    retrieval_cache_keys: tuple[str, ...] = ()
    shared_tool_state_keys: tuple[str, ...] = ()
    failure_signature: str = ""  # canonical hash/label of the failure mode
    spans: tuple[str, ...] = field(default_factory=tuple)


def _link_reason(a: SessionRecord, b: SessionRecord) -> str | None:
    if a.user_id != b.user_id:
        return None
    if b.started_at <= a.started_at:
        return None
    shared_cache = set(a.retrieval_cache_keys) & set(b.retrieval_cache_keys)
    if shared_cache:
        return f"shared_retrieval_cache:{sorted(shared_cache)[0]}"
    shared_state = set(a.shared_tool_state_keys) & set(b.shared_tool_state_keys)
    if shared_state:
        return f"shared_tool_state:{sorted(shared_state)[0]}"
    return None


def detect_contamination(sessions: list[SessionRecord]) -> list[CheckResult]:
    """Find pairs (A, B) where A failed first and B inherited shared state.

    For each user, scan failed sessions in time order; for each later
    session that shares retrieval/state keys, emit
    CROSS_SESSION_CONTAMINATION.
    """
    by_user: dict[str, list[SessionRecord]] = defaultdict(list)
    for s in sessions:
        by_user[s.user_id].append(s)

    out: list[CheckResult] = []
    for user_id, items in by_user.items():
        items_sorted = sorted(items, key=lambda s: s.started_at)
        for i, a in enumerate(items_sorted):
            if not a.failed:
                continue
            for b in items_sorted[i + 1 :]:
                reason = _link_reason(a, b)
                if reason is None:
                    continue
                out.append(
                    CheckResult(
                        check_type=CheckType.CROSS_SESSION_CONTAMINATION,
                        status=Status.WARN,
                        weight=1.0,
                        points_earned=0.0,
                        points_possible=1.0,
                        evidence=[
                            SpanRef(span_id=a.session_id),
                            SpanRef(span_id=b.session_id),
                        ],
                        category=Category.SAFETY,
                        meta={
                            "user_id": user_id,
                            "earlier_session": a.session_id,
                            "later_session": b.session_id,
                            "reason": reason,
                            "earlier_failure_signature": a.failure_signature,
                        },
                    )
                )
    return out
