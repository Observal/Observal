# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for SEC-023: cache key isolation per authenticated user."""

from unittest.mock import MagicMock


def _make_request(auth: str | None = None, path: str = "/api/v1/sessions", qs: str = "") -> MagicMock:
    req = MagicMock()
    req.url.path = path
    req.query_params = qs
    req.headers = {"authorization": auth} if auth else {}
    return req


class TestCacheKeyIsolation:
    def test_different_tokens_produce_different_keys(self):
        """Two users hitting the same path must get different cache keys."""
        from services.cache import _request_key_builder

        key_alice = _request_key_builder(lambda: None, request=_make_request("Bearer token-alice"))
        key_bob = _request_key_builder(lambda: None, request=_make_request("Bearer token-bob"))
        assert key_alice != key_bob

    def test_same_token_produces_same_key(self):
        """The same token always maps to the same cache slot (deterministic)."""
        from services.cache import _request_key_builder

        k1 = _request_key_builder(lambda: None, request=_make_request("Bearer same-token"))
        k2 = _request_key_builder(lambda: None, request=_make_request("Bearer same-token"))
        assert k1 == k2

    def test_anonymous_request_uses_anon_identity(self):
        """Unauthenticated requests get a distinct key from authenticated ones."""
        from services.cache import _request_key_builder

        key_anon = _request_key_builder(lambda: None, request=_make_request(None))
        key_authed = _request_key_builder(lambda: None, request=_make_request("Bearer some-token"))
        assert key_anon != key_authed

    def test_anonymous_requests_share_cache_bucket(self):
        """Two anonymous requests for the same path share a cache entry."""
        from services.cache import _request_key_builder

        k1 = _request_key_builder(lambda: None, request=_make_request(None))
        k2 = _request_key_builder(lambda: None, request=_make_request(None))
        assert k1 == k2

    def test_raw_token_not_in_key(self):
        """The bearer token itself must not appear in the cache key."""
        from services.cache import _request_key_builder

        token = "super-secret-bearer-token-value"
        key = _request_key_builder(lambda: None, request=_make_request(f"Bearer {token}"))
        assert token not in key

    def test_different_paths_different_keys(self):
        """Path is still part of the key — different routes don't collide."""
        from services.cache import _request_key_builder

        k1 = _request_key_builder(lambda: None, request=_make_request("Bearer tok", path="/api/v1/sessions"))
        k2 = _request_key_builder(lambda: None, request=_make_request("Bearer tok", path="/api/v1/dashboard"))
        assert k1 != k2
