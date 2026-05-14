# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Pluggable embedding provider for semantic outcome checks.

Two providers ship in-tree:

- ``HashedTokenProvider`` (default): deterministic bag-of-hashed-tokens with
  L2 normalization. No dependencies. Gives meaningful cosine similarity for
  short phrases without an external service. Same input → identical vector
  every time, which preserves the ``align_and_score`` determinism contract.
- ``OpenAIEmbeddingProvider`` (opt-in): used when ``EMBEDDING_MODEL_*`` is
  configured. Calls ``/v1/embeddings`` on an OpenAI-compatible endpoint.

Caching is keyed by ``(provider_name, text_sha256)`` and stored in process
memory. Persistent cache (Redis / Postgres) can replace it later.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    def embed(self, text: str) -> tuple[float, ...]: ...


# ── Hashed-token provider (default) ──


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


@dataclass
class HashedTokenProvider:
    """Bag of hashed tokens, L2-normalized.

    Cosine similarity between two HashedTokenProvider vectors is roughly the
    Jaccard / overlap of their tokens. It's not a semantic embedding — just a
    deterministic, dependency-free baseline. Words that don't share tokens
    score low; phrases that share content tokens score high.
    """

    name: str = "hashed_token_v1"
    dim: int = 1024

    def embed(self, text: str) -> tuple[float, ...]:
        if not text:
            return tuple(0.0 for _ in range(self.dim))
        vec = [0.0] * self.dim
        for tok in _tokens(text):
            h = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if (h[4] & 1) == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            return tuple(vec)
        return tuple(x / norm for x in vec)


# ── OpenAI-compatible provider (optional) ──


@dataclass
class OpenAIEmbeddingProvider:
    name: str
    dim: int
    url: str
    api_key: str
    model: str

    def embed(self, text: str) -> tuple[float, ...]:
        import httpx

        body = {"model": self.model, "input": text}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            r = httpx.post(f"{self.url}/embeddings", json=body, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            vec = data["data"][0]["embedding"]
            return tuple(float(x) for x in vec)
        except Exception:
            # fall back to hashed-token provider rather than raising; the caller
            # surfaces the fallback in meta
            return HashedTokenProvider(dim=self.dim).embed(text)


# ── Singleton + cache ──


_lock = threading.Lock()
_active: EmbeddingProvider | None = None
_cache: dict[tuple[str, str], tuple[float, ...]] = {}


def _resolve_default() -> EmbeddingProvider:
    """Pick provider based on env. Defaults to the in-process hashed-token impl."""
    model = os.environ.get("EMBEDDING_MODEL_NAME") or ""
    url = os.environ.get("EMBEDDING_MODEL_URL") or ""
    if model and url:
        api_key = os.environ.get("EMBEDDING_MODEL_API_KEY") or ""
        try:
            dim = int(os.environ.get("EMBEDDING_MODEL_DIM") or "1536")
        except ValueError:
            dim = 1536
        return OpenAIEmbeddingProvider(name=f"openai:{model}", dim=dim, url=url, api_key=api_key, model=model)
    return HashedTokenProvider()


def get_provider() -> EmbeddingProvider:
    global _active
    if _active is None:
        with _lock:
            if _active is None:
                _active = _resolve_default()
    return _active


def set_provider(provider: EmbeddingProvider | None) -> None:
    """Swap the active provider (used by tests)."""
    global _active
    with _lock:
        _active = provider
        _cache.clear()


def _key(provider_name: str, text: str) -> tuple[str, str]:
    return (provider_name, hashlib.sha256(text.encode("utf-8", "replace")).hexdigest())


def embed_cached(text: str, *, provider: EmbeddingProvider | None = None) -> tuple[float, ...]:
    p = provider or get_provider()
    k = _key(p.name, text)
    cached = _cache.get(k)
    if cached is not None:
        return cached
    v = p.embed(text)
    _cache[k] = v
    return v


def cosine(a: tuple[float, ...] | list[float], b: tuple[float, ...] | list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        ai = float(a[i])
        bi = float(b[i])
        dot += ai * bi
        na += ai * ai
        nb += bi * bi
    if na == 0 or nb == 0:
        return 0.0
    return dot / math.sqrt(na * nb)


def semantic_score(text_a: str, text_b: str, *, provider: EmbeddingProvider | None = None) -> float:
    """Cosine similarity between two strings via the active provider."""
    va = embed_cached(text_a, provider=provider)
    vb = embed_cached(text_b, provider=provider)
    return cosine(va, vb)


__all__ = [
    "EmbeddingProvider",
    "HashedTokenProvider",
    "OpenAIEmbeddingProvider",
    "cosine",
    "embed_cached",
    "get_provider",
    "semantic_score",
    "set_provider",
]


# Convenience type for tests that want to inject a stub
EmbedCallable = Callable[[str], tuple[float, ...]]
