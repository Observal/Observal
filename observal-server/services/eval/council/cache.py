# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""In-memory cache for Council facts.

Cache key is `(span_id, question_id, model_snapshot)` per the unified
prompt: same input + same model snapshot = same fact = same CheckResult.
The cache stores facts (structured), never scores. A persistent backing
store can be plugged in by subclassing; default is a process-local dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FactCacheKey:
    span_id: str
    question_id: str
    model_snapshot: str


class CouncilCache:
    def __init__(self) -> None:
        self._store: dict[FactCacheKey, dict[str, Any]] = {}
        self._hits = 0
        self._misses = 0

    def get(self, key: FactCacheKey) -> dict[str, Any] | None:
        if key in self._store:
            self._hits += 1
            return self._store[key]
        self._misses += 1
        return None

    def put(self, key: FactCacheKey, fact: dict[str, Any]) -> None:
        self._store[key] = fact

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses
