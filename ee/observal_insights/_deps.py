"""Dependency container — wired up by the host application at startup.

The insights package does NOT import from observal-server directly.
Instead, the main app calls configure() which injects these dependencies.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

# These are set by configure() at application startup
settings: Any = None
query: Callable[..., Awaitable[Any]] | None = None  # ClickHouse query fn
call_model: Callable[..., Awaitable[dict]] | None = None  # LLM model call fn
db_session: Callable[..., Any] | None = None  # async_session factory

# Model classes (set by configure())
InsightSessionFacets: type | None = None
InsightSessionMeta: type | None = None
InsightMetaCache: type | None = None


def get_settings():
    if settings is None:
        raise RuntimeError("observal_insights not configured. Call configure() first.")
    return settings


def get_query():
    if query is None:
        raise RuntimeError("observal_insights not configured. Call configure() first.")
    return query


def get_call_model():
    if call_model is None:
        raise RuntimeError("observal_insights not configured. Call configure() first.")
    return call_model


def get_db_session():
    if db_session is None:
        raise RuntimeError("observal_insights not configured. Call configure() first.")
    return db_session


def get_facets_model():
    if InsightSessionFacets is None:
        raise RuntimeError("observal_insights not configured. Call configure() first.")
    return InsightSessionFacets


def get_meta_model():
    if InsightSessionMeta is None:
        raise RuntimeError("observal_insights not configured. Call configure() first.")
    return InsightSessionMeta


def get_meta_cache_model():
    if InsightMetaCache is None:
        raise RuntimeError("observal_insights not configured. Call configure() first.")
    return InsightMetaCache
