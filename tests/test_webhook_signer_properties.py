# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Property-based tests for webhook_signer correctness properties.

Uses hypothesis to validate universal properties hold for all valid inputs.
"""

import time
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from services.webhook_signer import sign_payload, verify_signature

# Strategy for valid secrets (non-empty strings)
secrets_st = st.text(min_size=1, max_size=128, alphabet=st.characters(categories=("L", "N", "P")))
# Strategy for valid timestamps
timestamps_st = st.integers(min_value=1, max_value=2**31)
# Strategy for payload bodies
bodies_st = st.binary(min_size=0, max_size=4096)


class TestProperty1SigningRoundTrip:
    """∀ (secret, timestamp, body): verify(secret, sign(secret, ts, body), ts, body) == True."""

    @given(secret=secrets_st, timestamp=timestamps_st, body=bodies_st)
    @settings(max_examples=200)
    def test_sign_then_verify_always_true(self, secret, timestamp, body):
        """Signing round-trip: sign then verify returns True within tolerance."""
        sig = sign_payload(secret, timestamp, body)
        # Patch time to be exactly at the timestamp so it's within tolerance
        with patch("services.webhook_signer.time") as mock_time:
            mock_time.time.return_value = timestamp
            assert verify_signature(secret, sig, timestamp, body) is True


class TestProperty2TamperDetection:
    """∀ (secret, body, body') where body ≠ body': verify(secret, sign(secret, ts, body), ts, body') == False."""

    @given(secret=secrets_st, body=bodies_st, tampered_body=bodies_st)
    @settings(max_examples=200)
    def test_tampered_body_always_rejected(self, secret, body, tampered_body):
        """Any modification to the body invalidates the signature."""
        if body == tampered_body:
            return  # Skip when hypothesis generates identical bodies
        ts = int(time.time())
        sig = sign_payload(secret, ts, body)
        assert verify_signature(secret, sig, ts, tampered_body) is False


class TestProperty3WrongSecretRejection:
    """∀ (secret, secret') where secret ≠ secret': verify(secret', sign(secret, ts, body), ts, body) == False."""

    @given(secret=secrets_st, wrong_secret=secrets_st, body=bodies_st)
    @settings(max_examples=200)
    def test_wrong_secret_always_rejected(self, secret, wrong_secret, body):
        """A different secret always produces verification failure."""
        if secret == wrong_secret:
            return  # Skip when hypothesis generates identical secrets
        ts = int(time.time())
        sig = sign_payload(secret, ts, body)
        assert verify_signature(wrong_secret, sig, ts, body) is False
