# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Shape discovery entries into the JSON the ARD endpoints return."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from models.discovery_entry import DiscoveryEntry, DiscoveryKind, DiscoveryLifecycle
from services.discovery.identity import MEDIA_TYPE_REGISTRY, build_registry_urn, identity_uri

if TYPE_CHECKING:
    from services.discovery.search import Ranked

RESULT_DESCRIPTION_LIMIT = 280

# What a caller can do with the entry right now, from the CLI's point of view.
AVAILABILITY_NOW = "now"  # text resource, loads into the current session
AVAILABILITY_NEXT_SESSION = "next-session"  # config write, takes effect after restart
AVAILABILITY_EXPLICIT = "explicit-install"  # hooks: never activated implicitly
AVAILABILITY_NOT_APPROVED = "not-approved"
AVAILABILITY_ARCHIVED = "archived"
AVAILABILITY_UNSUPPORTED = "unsupported-in-harness"

_NOW_KINDS = {DiscoveryKind.skill, DiscoveryKind.prompt}


def availability(entry: DiscoveryEntry, harness: str | None = None) -> str:
    if entry.lifecycle_status == DiscoveryLifecycle.archived:
        return AVAILABILITY_ARCHIVED
    if entry.lifecycle_status != DiscoveryLifecycle.approved:
        return AVAILABILITY_NOT_APPROVED
    if harness and entry.supported_harnesses and harness not in entry.supported_harnesses:
        return AVAILABILITY_UNSUPPORTED
    if entry.kind == DiscoveryKind.hook:
        return AVAILABILITY_EXPLICIT
    if entry.kind in _NOW_KINDS:
        return AVAILABILITY_NOW
    return AVAILABILITY_NEXT_SESSION


def _truncate(text: str | None, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def search_result_item(ranked: Ranked, *, source: str, harness: str | None = None) -> dict[str, Any]:
    """One entry of ``results`` in an ARD Search response.

    Only ``identifier`` is required by the spec; we include what a client
    needs to choose without a second request, and keep ``score`` relevance-only.
    """
    entry = ranked.entry
    return {
        "identifier": entry.ard_identifier,
        "displayName": entry.display_name,
        "type": entry.media_type,
        "url": entry.artifact_url,
        "version": entry.version,
        "description": _truncate(entry.description, RESULT_DESCRIPTION_LIMIT),
        "capabilities": list(entry.capabilities or [])[:8],
        "score": int(ranked.score),
        "source": source,
        "matchedOn": list(ranked.matched_on),
        "obs:kind": entry.kind.value,
        "obs:nativeRef": entry.native_ref,
        "obs:approval": entry.lifecycle_status.value,
        "obs:visibility": entry.visibility.value,
        "obs:supportedHarnesses": list(entry.supported_harnesses or []),
        "obs:availability": availability(entry, harness),
        "obs:activatable": bool(entry.activatable),
        "obs:artifactDigest": entry.artifact_digest,
        "obs:publisher": entry.publisher_domain,
    }


def entry_document(entry: DiscoveryEntry) -> dict[str, Any]:
    """The complete ARD entry as published (``raw_entry`` is rebuilt on every change)."""
    return dict(entry.raw_entry or {})


def registry_entry(publisher_domain: str, base_url: str, *, display_name: str = "Observal") -> dict[str, Any]:
    """The ``application/ai-registry+json`` entry that advertises this registry's search base."""
    return {
        "identifier": build_registry_urn(publisher_domain),
        "displayName": f"{display_name} Registry",
        "type": MEDIA_TYPE_REGISTRY,
        "url": f"{base_url.rstrip('/')}/api/v1/ard",
        "description": "Observal discovery registry: search approved agents, MCP servers, skills, hooks, prompts and sandboxes.",
        "representativeQueries": [
            "find an approved skill for reviewing pull requests",
            "which MCP servers can query our database",
        ],
        "trustManifest": {"identity": identity_uri(publisher_domain), "identityType": "https"},
    }


def manifest(entries: list[DiscoveryEntry], *, publisher_domain: str, base_url: str) -> dict[str, Any]:
    """The ``/.well-known/ard.json`` document: registry entry first, then resources."""
    return {
        "@context": ["https://agenticresourcediscovery.org/context/v1", {"obs": "https://observal.io/ns#"}],
        "entries": [registry_entry(publisher_domain, base_url), *(entry_document(e) for e in entries)],
    }


def list_item(entry: DiscoveryEntry) -> dict[str, Any]:
    """Compact row for ARD List (``GET /agents``)."""
    return {
        "identifier": entry.ard_identifier,
        "displayName": entry.display_name,
        "type": entry.media_type,
        "url": entry.artifact_url,
        "version": entry.version,
        "description": _truncate(entry.description, RESULT_DESCRIPTION_LIMIT),
        "obs:kind": entry.kind.value,
        "obs:nativeRef": entry.native_ref,
        "obs:approval": entry.lifecycle_status.value,
        "obs:supportedHarnesses": list(entry.supported_harnesses or []),
        "updatedAt": entry.updated_at_source.isoformat() if entry.updated_at_source else None,
    }
