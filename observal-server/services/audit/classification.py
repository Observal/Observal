# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Route sensitivity classification for audit logging."""

from __future__ import annotations

_PATTERNS: list[tuple[str, str]] = [
    ("/livez", "skip"),
    ("/healthz", "skip"),
    ("/readyz", "skip"),
    ("/health", "skip"),
    ("/metrics", "skip"),
    ("/.well-known/jwks.json", "skip"),
    ("/docs", "skip"),
    ("/redoc", "skip"),
    ("/openapi.json", "skip"),
    ("/api/v1/sessions", "phi_adjacent"),
    ("/api/v1/ingest", "phi_adjacent"),
    ("/api/v1/reconcile", "phi_adjacent"),
    ("/api/v1/telemetry", "phi_adjacent"),
    ("/api/v1/admin", "admin"),
    ("/api/v1/agents", "high"),
    ("/api/v1/mcps", "high"),
    ("/api/v1/auth", "high"),
    ("/api/v1/device-auth", "high"),
    ("/api/v1/feedback", "standard"),
    ("/api/v1/dashboard", "standard"),
    ("/api/v1/skills", "standard"),
    ("/api/v1/hooks", "standard"),
    ("/api/v1/prompts", "standard"),
    ("/api/v1/sandboxes", "standard"),
    ("/api/v1/review", "standard"),
    ("/api/v1/alerts", "standard"),
    ("/api/v1/eval", "standard"),
    ("/api/v1/insights", "standard"),
    ("/api/v1/bulk", "standard"),
    ("/api/v1/graphql", "standard"),
    ("/api/v1/config", "low"),
]


def classify_route(method: str, path: str) -> str:
    """Return sensitivity level for a given route."""
    for pattern, level in _PATTERNS:
        if path == pattern or path.startswith(pattern + "/") or path.startswith(pattern + "?"):
            return level
    if path.startswith("/api/"):
        return "standard"
    return "skip"
