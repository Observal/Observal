# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Small keyword search helpers for registry list endpoints."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

from sqlalchemy import case, literal, or_

from api.sanitize import escape_like

_KEEP_TINY = {"ai", "go", "js", "ts", "ui", "ux"}
_STOP_WORDS = {
    "about",
    "agent",
    "all",
    "and",
    "any",
    "are",
    "component",
    "components",
    "could",
    "find",
    "for",
    "from",
    "good",
    "help",
    "helps",
    "install",
    "into",
    "make",
    "mcp",
    "me",
    "need",
    "please",
    "registry",
    "server",
    "skill",
    "skills",
    "setup",
    "that",
    "the",
    "this",
    "what",
    "when",
    "with",
    "would",
    "you",
}


def keyword_tokens(query: str | None) -> list[str]:
    """Tokenize a natural-ish query into useful search words."""
    if not query:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[a-z0-9][a-z0-9_-]*", query.lower()):
        token = raw.strip("-_")
        if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
            token = token[:-1]
        if (len(token) < 3 and token not in _KEEP_TINY) or token in _STOP_WORDS:
            continue
        if token not in seen:
            out.append(token)
            seen.add(token)
    return out


def keyword_search(query: str | None, fields: Sequence[Any], *, name_field: Any | None = None) -> tuple[Any | None, Any | None]:
    """Return ``(where_clause, rank_expr)`` for token OR search.

    The rank is intentionally simple: phrase/name hits first, then token hits.
    """
    tokens = keyword_tokens(query)
    if not tokens:
        return None, None

    phrase = " ".join(tokens)
    terms = [phrase, *[t for t in tokens if t != phrase]]
    clauses = [field.ilike(f"%{escape_like(term)}%") for term in terms for field in fields]
    rank = literal(0)

    if name_field is not None:
        rank += case((name_field.ilike(f"%{escape_like(phrase)}%"), 100), else_=0)
    for field in fields:
        rank += case((field.ilike(f"%{escape_like(phrase)}%"), 40), else_=0)
    for token in tokens:
        if name_field is not None:
            rank += case((name_field.ilike(f"%{escape_like(token)}%"), 12), else_=0)
        for field in fields:
            rank += case((field.ilike(f"%{escape_like(token)}%"), 4), else_=0)

    return or_(*clauses), rank
