# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for webhook_signer module."""

import time
from unittest.mock import patch

from services.webhook_signer import (
    HEADER_EVENT_ID,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    build_headers,
    sign_payload,
    verify_signature,
)


class TestSignPayload:
    def test_returns_64_char_hex(self):
        sig = sign_payload("secret", 1000000, b"hello")
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_deterministic(self):
        sig1 = sign_payload("secret", 1000000, b"body")
        sig2 = sign_payload("secret", 1000000, b"body")
        assert sig1 == sig2

    def test_different_secret_different_sig(self):
        sig1 = sign_payload("secret1", 1000000, b"body")
        sig2 = sign_payload("secret2", 1000000, b"body")
        assert sig1 != sig2

    def test_different_body_different_sig(self):
        sig1 = sign_payload("secret", 1000000, b"body1")
        sig2 = sign_payload("secret", 1000000, b"body2")
        assert sig1 != sig2

    def test_different_timestamp_different_sig(self):
        sig1 = sign_payload("secret", 1000000, b"body")
        sig2 = sign_payload("secret", 1000001, b"body")
        assert sig1 != sig2

    def test_empty_body(self):
        sig = sign_payload("secret", 1000000, b"")
        assert len(sig) == 64


class TestBuildHeaders:
    def test_contains_all_headers(self):
        headers = build_headers("secret", b"payload")
        assert HEADER_SIGNATURE in headers
        assert HEADER_TIMESTAMP in headers
        assert HEADER_EVENT_ID in headers

    def test_signature_has_sha256_prefix(self):
        headers = build_headers("secret", b"payload")
        assert headers[HEADER_SIGNATURE].startswith("sha256=")

    def test_timestamp_is_numeric_string(self):
        headers = build_headers("secret", b"payload")
        assert headers[HEADER_TIMESTAMP].isdigit()

    def test_event_id_is_uuid_format(self):
        headers = build_headers("secret", b"payload")
        event_id = headers[HEADER_EVENT_ID]
        # UUID4 format: 8-4-4-4-12 hex chars
        parts = event_id.split("-")
        assert len(parts) == 5
        assert [len(p) for p in parts] == [8, 4, 4, 4, 12]

    def test_signature_is_verifiable(self):
        headers = build_headers("mysecret", b"test body")
        sig = headers[HEADER_SIGNATURE].removeprefix("sha256=")
        ts = int(headers[HEADER_TIMESTAMP])
        assert verify_signature("mysecret", sig, ts, b"test body")


class TestVerifySignature:
    def test_round_trip(self):
        """Sign then verify returns True (Correctness Property 1)."""
        secret = "a1b2c3d4e5f6"
        ts = int(time.time())
        body = b'{"alert": "test"}'
        sig = sign_payload(secret, ts, body)
        assert verify_signature(secret, sig, ts, body) is True

    def test_tampered_payload_rejected(self):
        """Modified body after signing returns False (Correctness Property 2)."""
        secret = "secret123"
        ts = int(time.time())
        sig = sign_payload(secret, ts, b"original")
        assert verify_signature(secret, sig, ts, b"tampered") is False

    def test_wrong_secret_rejected(self):
        """Different secret returns False (Correctness Property 3)."""
        ts = int(time.time())
        body = b"payload"
        sig = sign_payload("correct_secret", ts, body)
        assert verify_signature("wrong_secret", sig, ts, body) is False

    def test_expired_timestamp_rejected(self):
        """Old timestamp returns False (Correctness Property 4)."""
        secret = "secret"
        old_ts = int(time.time()) - 600  # 10 minutes ago
        body = b"payload"
        sig = sign_payload(secret, old_ts, body)
        assert verify_signature(secret, sig, old_ts, body) is False

    def test_future_timestamp_rejected(self):
        """Future timestamp beyond tolerance returns False."""
        secret = "secret"
        future_ts = int(time.time()) + 600  # 10 minutes in future
        body = b"payload"
        sig = sign_payload(secret, future_ts, body)
        assert verify_signature(secret, sig, future_ts, body) is False

    def test_custom_tolerance(self):
        """Custom tolerance window is respected."""
        secret = "secret"
        ts = int(time.time()) - 10  # 10 seconds ago
        body = b"payload"
        sig = sign_payload(secret, ts, body)
        # Should pass with 30s tolerance
        assert verify_signature(secret, sig, ts, body, tolerance_seconds=30) is True
        # Should fail with 5s tolerance
        assert verify_signature(secret, sig, ts, body, tolerance_seconds=5) is False

    def test_timestamp_at_boundary(self):
        """Timestamp exactly at tolerance boundary passes."""
        secret = "secret"
        body = b"payload"
        now = int(time.time())
        sig = sign_payload(secret, now, body)
        with patch("services.webhook_signer.time") as mock_time:
            mock_time.time.return_value = now + 300  # Exactly at boundary
            assert verify_signature(secret, sig, now, body, tolerance_seconds=300) is True

    def test_empty_body_round_trip(self):
        """Empty body signs and verifies correctly."""
        secret = "secret"
        ts = int(time.time())
        sig = sign_payload(secret, ts, b"")
        assert verify_signature(secret, sig, ts, b"") is True
