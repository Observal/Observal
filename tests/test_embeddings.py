# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Embedding provider + semantic match tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server"))

from services.eval.alignment.engine import align_and_score
from services.eval.alignment.outcome_checks import check_response_contains
from services.eval.check_result.models import CheckType
from services.eval.embeddings import (
    HashedTokenProvider,
    OpenAIEmbeddingProvider,
    cosine,
    embed_cached,
    get_provider,
    semantic_score,
    set_provider,
)
from services.eval.spec_dag.models import (
    OutcomeAssertion,
    OutcomeCheck,
    OutcomeCheckType,
    SpecDAG,
    SpecSource,
)
from services.eval.trace_dag.builder import build_trace_dag


def _final(text: str):
    return {
        "span_id": "z",
        "trace_id": "t",
        "parent_span_id": None,
        "type": "agent_to_user",
        "name": "respond",
        "method": "",
        "input": None,
        "output": text,
        "output_excerpt": text[:128],
        "tool_result_hash": None,
        "files_read": [],
        "files_written": [],
        "intent_label": None,
        "references": [],
        "start_time": 1,
        "end_time": 2,
        "status": "success",
        "metadata": {},
    }


# ── HashedTokenProvider ──


class TestHashedTokenProvider:
    def test_dim_matches(self):
        p = HashedTokenProvider(dim=512)
        v = p.embed("hello world")
        assert len(v) == 512

    def test_l2_normalized(self):
        v = HashedTokenProvider().embed("apple banana cherry")
        norm = sum(x * x for x in v) ** 0.5
        assert abs(norm - 1.0) < 1e-9

    def test_empty_returns_zero_vector(self):
        v = HashedTokenProvider().embed("")
        assert all(x == 0 for x in v)

    def test_deterministic(self):
        a = HashedTokenProvider().embed("the quick brown fox")
        b = HashedTokenProvider().embed("the quick brown fox")
        assert a == b


class TestCosineSimilarity:
    def test_identical_text_high_similarity(self):
        p = HashedTokenProvider()
        a = p.embed("here is the answer")
        b = p.embed("here is the answer")
        assert cosine(a, b) > 0.99

    def test_unrelated_text_low_similarity(self):
        p = HashedTokenProvider()
        a = p.embed("the cat sat on the mat")
        b = p.embed("zylophone hyperion mercury jurisprudence")
        assert cosine(a, b) < 0.5

    def test_overlap_scales_similarity(self):
        p = HashedTokenProvider()
        a = p.embed("the cat sat on the mat")
        b = p.embed("the cat sat on the bench")  # 4/6 tokens shared
        c = p.embed("crystals shimmer in moonlight")  # disjoint
        sim_ab = cosine(a, b)
        sim_ac = cosine(a, c)
        assert sim_ab > sim_ac
        assert sim_ab > 0.5

    def test_zero_vector_yields_zero(self):
        assert cosine((0.0, 0.0), (1.0, 0.0)) == 0.0


# ── Cache ──


class TestCache:
    def test_repeated_calls_return_same_object(self):
        set_provider(HashedTokenProvider())
        a = embed_cached("hello world")
        b = embed_cached("hello world")
        assert a is b
        set_provider(None)

    def test_set_provider_clears_cache(self):
        set_provider(HashedTokenProvider())
        embed_cached("hello world")
        set_provider(HashedTokenProvider(dim=128))
        v = embed_cached("hello world")
        assert len(v) == 128
        set_provider(None)


class TestOpenAIEmbeddingProvider:
    def test_env_resolution_and_failed_http_falls_back(self, monkeypatch):
        import httpx

        def fail_post(*args, **kwargs):
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(httpx, "post", fail_post)
        monkeypatch.setenv("EMBEDDING_MODEL_NAME", "tiny")
        monkeypatch.setenv("EMBEDDING_MODEL_URL", "http://127.0.0.1:9/v1")
        monkeypatch.setenv("EMBEDDING_MODEL_API_KEY", "key")
        monkeypatch.setenv("EMBEDDING_MODEL_DIM", "not-an-int")
        set_provider(None)
        try:
            provider = get_provider()
            assert provider.name == "openai:tiny"
            assert provider.dim == 1536
            vec = provider.embed("fallback text")
            assert len(vec) == 1536
        finally:
            monkeypatch.delenv("EMBEDDING_MODEL_NAME", raising=False)
            monkeypatch.delenv("EMBEDDING_MODEL_URL", raising=False)
            monkeypatch.delenv("EMBEDDING_MODEL_API_KEY", raising=False)
            monkeypatch.delenv("EMBEDDING_MODEL_DIM", raising=False)
            set_provider(None)

    def test_successful_openai_response_is_normalized_to_tuple(self, monkeypatch):
        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"embedding": [1, "2.5", 3]}]}

        def fake_post(url, json, headers, timeout):
            assert url == "http://embeddings.local/embeddings"
            assert json == {"model": "m", "input": "hello"}
            assert headers["Authorization"] == "Bearer secret"
            assert timeout == 15
            return _Response()

        import httpx

        monkeypatch.setattr(httpx, "post", fake_post)
        provider = OpenAIEmbeddingProvider(
            name="openai:m", dim=3, url="http://embeddings.local", api_key="secret", model="m"
        )

        assert provider.embed("hello") == (1.0, 2.5, 3.0)


# ── Stub provider injection ──


class _StubProvider:
    name = "stub"
    dim = 4

    def __init__(self):
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        # 1.0 if text contains "answer", else 0.0 — easy to score
        return (1.0, 0.0, 0.0, 0.0) if "answer" in text.lower() else (0.0, 0.0, 0.0, 1.0)


class TestStubProviderUsedByOutcomeCheck:
    def test_semantic_match_passes_when_cosine_meets_threshold(self):
        stub = _StubProvider()
        set_provider(stub)
        try:
            spans = [_final("here is the answer for you")]
            dag = build_trace_dag(spans)
            passed, meta = check_response_contains(
                dag,
                {
                    "pattern": "answer",
                    "match_type": "semantic",
                    "threshold": 0.5,
                },
            )
            assert passed
            assert meta["match_type"] == "semantic"
            assert meta["cosine"] == 1.0
            assert meta["provider"] == "stub"
        finally:
            set_provider(None)

    def test_semantic_match_fails_when_unrelated(self):
        set_provider(_StubProvider())
        try:
            spans = [_final("the response is rectangular")]
            dag = build_trace_dag(spans)
            passed, meta = check_response_contains(
                dag,
                {
                    "pattern": "answer",
                    "match_type": "semantic",
                    "threshold": 0.5,
                },
            )
            assert not passed
            assert meta["cosine"] == 0.0
        finally:
            set_provider(None)


# ── End-to-end alignment with semantic match ──


class TestAlignmentSemanticEndToEnd:
    def test_passes_with_high_overlap(self):
        spec = SpecDAG(
            task_type="t",
            version="1",
            source=SpecSource.HAND_AUTHORED,
            outcome_assertions=[
                OutcomeAssertion(
                    assertion_id="x",
                    check=OutcomeCheck(
                        check_type=OutcomeCheckType.RESPONSE_CONTAINS,
                        params={
                            "pattern": "the order has been cancelled",
                            "match_type": "semantic",
                            "threshold": 0.4,
                        },
                    ),
                    weight=1.0,
                    required=True,
                ),
            ],
        )
        spans = [_final("Confirmed — the order has been cancelled successfully.")]
        dag = build_trace_dag(spans)
        result = align_and_score(spec, dag)
        assert result.correctness_score == 1.0
        matched = next(c for c in result.check_results if c.check_type == CheckType.MATCHED)
        assert matched.meta["cosine"] >= 0.4

    def test_fails_when_unrelated(self):
        spec = SpecDAG(
            task_type="t",
            version="1",
            source=SpecSource.HAND_AUTHORED,
            outcome_assertions=[
                OutcomeAssertion(
                    assertion_id="x",
                    check=OutcomeCheck(
                        check_type=OutcomeCheckType.RESPONSE_CONTAINS,
                        params={
                            "pattern": "order cancelled",
                            "match_type": "semantic",
                            "threshold": 0.6,
                        },
                    ),
                    weight=1.0,
                    required=True,
                ),
            ],
        )
        spans = [_final("Pineapples grow in tropical climates and require irrigation.")]
        dag = build_trace_dag(spans)
        result = align_and_score(spec, dag)
        assert result.correctness_score < 1.0


# ── Determinism preserved ──


class TestSemanticMatchIsDeterministic:
    def test_100_runs(self):
        spec = SpecDAG(
            task_type="t",
            version="1",
            source=SpecSource.HAND_AUTHORED,
            outcome_assertions=[
                OutcomeAssertion(
                    assertion_id="x",
                    check=OutcomeCheck(
                        check_type=OutcomeCheckType.RESPONSE_CONTAINS,
                        params={"pattern": "answer", "match_type": "semantic", "threshold": 0.3},
                    ),
                    weight=1.0,
                    required=True,
                ),
            ],
        )
        spans = [_final("here is the answer to your question")]
        dag = build_trace_dag(spans)
        first = align_and_score(spec, dag)
        for _ in range(99):
            again = align_and_score(spec, dag)
            assert again.correctness_score == first.correctness_score
            assert [c.model_dump() for c in again.check_results] == [c.model_dump() for c in first.check_results]


# ── Default provider resolution ──


class TestProviderResolution:
    def test_default_is_hashed_token(self):
        set_provider(None)
        p = get_provider()
        try:
            assert p.name.startswith("hashed_token")
        finally:
            set_provider(None)


class TestSemanticScoreHelper:
    def test_helper_matches_provider(self):
        set_provider(HashedTokenProvider())
        try:
            score = semantic_score("the cat sat on the mat", "the cat sat on the mat")
            assert score > 0.99
        finally:
            set_provider(None)
