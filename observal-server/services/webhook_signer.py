# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""HMAC-SHA256 webhook signing and verification utility.

Implements the GitHub/Stripe/Svix signing convention:
- X-Observal-Signature: sha256=<hex_digest>
- X-Observal-Timestamp: <unix_epoch_seconds>
- X-Observal-Event-Id: <uuid4> (for receiver-side idempotency)

Signature is computed as HMAC-SHA256(secret, "{timestamp}.{body}").
"""

import hashlib
import hmac
import time
import uuid

HEADER_SIGNATURE = "X-Observal-Signature"
HEADER_TIMESTAMP = "X-Observal-Timestamp"
HEADER_EVENT_ID = "X-Observal-Event-Id"


def sign_payload(secret: str, timestamp: int, body: bytes) -> str:
    """Compute HMAC-SHA256 signature over "{timestamp}.{body}".

    Args:
        secret: Non-empty string (64-char hex recommended).
        timestamp: Positive integer, Unix epoch seconds.
        body: Raw bytes of the payload (may be empty).

    Returns:
        64-character lowercase hex string.
    """
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def build_headers(secret: str, body: bytes) -> dict[str, str]:
    """Build signature headers for an outbound webhook request.

    Generates a fresh timestamp and event ID. Returns a dict with:
    - X-Observal-Signature (prefixed with "sha256=")
    - X-Observal-Timestamp (string of Unix epoch seconds)
    - X-Observal-Event-Id (UUID4 for receiver-side idempotency)

    Args:
        secret: Non-empty signing secret.
        body: Raw bytes of the serialized payload.

    Returns:
        Dict of header name -> header value.
    """
    timestamp = int(time.time())
    signature = sign_payload(secret, timestamp, body)
    event_id = str(uuid.uuid4())
    return {
        HEADER_SIGNATURE: f"sha256={signature}",
        HEADER_TIMESTAMP: str(timestamp),
        HEADER_EVENT_ID: event_id,
    }


def verify_signature(
    secret: str,
    signature: str,
    timestamp: int,
    body: bytes,
    tolerance_seconds: int = 300,
) -> bool:
    """Verify a webhook signature with constant-time comparison.

    Checks both timestamp freshness and HMAC validity.
    Fast-rejects expired timestamps before computing HMAC.

    Args:
        secret: The shared signing secret.
        signature: Hex-encoded signature to verify (without "sha256=" prefix).
        timestamp: The timestamp from X-Observal-Timestamp header.
        body: Raw bytes of the request body.
        tolerance_seconds: Maximum age of timestamp in seconds (default 5 min).

    Returns:
        True only if timestamp is fresh AND signature matches (constant-time).
    """
    now = int(time.time())
    if abs(now - timestamp) > tolerance_seconds:
        return False

    expected = sign_payload(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)
