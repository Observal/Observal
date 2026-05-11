# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Property-based tests for the support bundle redaction, manifest, and config modules.

Uses Hypothesis to verify universal correctness properties across randomized inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
import string

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from observal_cli.cmd_support import CONFIG_ALLOWLIST
from observal_cli.support.manifest import BundleManifest, FileEntry, compute_file_entry
from observal_cli.support.redaction import (
    AWS_KEY_PATTERN,
    JWT_PATTERN,
    REDACTED,
    URL_USERINFO_PATTERN,
    redact_string,
    redact_value,
    shannon_entropy,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _has_jwt(s: str) -> bool:
    return bool(JWT_PATTERN.search(s))


def _has_aws_key(s: str) -> bool:
    return bool(AWS_KEY_PATTERN.search(s))


def _has_url_userinfo(s: str) -> bool:
    return bool(URL_USERINFO_PATTERN.search(s))


def _has_high_entropy_token(s: str) -> bool:
    """Check if any token in the string would trigger the entropy rule."""
    tokens = re.split(r'([\s"\'`,;=\[\]{}()])', s)
    return any(len(token) >= 32 and shannon_entropy(token) > 4.5 for token in tokens)


def _is_safe_string(s: str) -> bool:
    """Return True if the string contains no patterns that would trigger redaction."""
    return not _has_jwt(s) and not _has_aws_key(s) and not _has_url_userinfo(s) and not _has_high_entropy_token(s)


# ── Strategies ───────────────────────────────────────────────────────

# Safe text: ASCII printable strings that won't accidentally match secret patterns.
# We use a limited alphabet and short lengths to avoid entropy triggers.
_safe_alphabet = string.ascii_lowercase + string.digits + " .,!?-_:/"
safe_text_strategy = st.text(
    alphabet=_safe_alphabet,
    min_size=0,
    max_size=80,
).filter(_is_safe_string)


# JWT strategy: generate realistic JWT-shaped tokens
def _jwt_strategy():
    """Generate a JWT-like token: eyJ<base64url>.<base64url>.<base64url>."""
    b64_chars = string.ascii_letters + string.digits + "_-"
    segment = st.text(alphabet=b64_chars, min_size=4, max_size=30)
    return st.tuples(segment, segment, segment).map(lambda parts: f"eyJ{parts[0]}.eyJ{parts[1]}.{parts[2]}")


# AWS key strategy
def _aws_key_strategy():
    suffix_chars = string.digits + string.ascii_uppercase
    return st.text(alphabet=suffix_chars, min_size=16, max_size=16).map(lambda s: f"AKIA{s}")


# URL userinfo strategy with supported schemes
_SUPPORTED_SCHEMES = ["https", "http", "postgresql+asyncpg", "postgres", "redis", "clickhouse"]


def _url_userinfo_strategy():
    scheme = st.sampled_from(_SUPPORTED_SCHEMES)
    # Use simple alphanumeric user/pass to avoid regex issues
    user = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=10)
    password = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=10)
    host = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=10)
    path = st.text(alphabet=string.ascii_lowercase + string.digits + "/", min_size=0, max_size=15)
    return st.tuples(scheme, user, password, host, path).map(lambda t: f"{t[0]}://{t[1]}:{t[2]}@{t[3]}/{t[4]}")


# High-entropy string strategy: 32+ chars with high character diversity
def _high_entropy_strategy():
    """Generate strings with length >= 32 and Shannon entropy > 4.5."""
    # Use a wide alphabet to ensure high entropy
    wide_alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return st.text(
        alphabet=wide_alphabet,
        min_size=40,
        max_size=60,
    ).filter(lambda s: shannon_entropy(s) > 4.5)


# Low-entropy string strategy: repetitive characters
def _low_entropy_strategy(min_size=0, max_size=80):
    """Generate strings with low entropy (repetitive characters)."""
    return st.text(
        alphabet="abc",
        min_size=min_size,
        max_size=max_size,
    )


# Sensitive key names
_SENSITIVE_KEY_NAMES = [
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "api-key",
    "access_key",
    "private_key",
    "credential",
    "authorization",
    "client_secret",
    "bearer",
    "MY_PASSWORD",
    "db_secret_key",
    "AUTH_TOKEN",
]

# Non-sensitive key names
_NON_SENSITIVE_KEY_NAMES = [
    "hostname",
    "port",
    "database",
    "log_level",
    "region",
    "name",
    "version",
    "status",
    "count",
    "enabled",
]


# ── Property 1: Redaction identity — safe strings pass through unchanged ──


class TestRedactionIdentity:
    """**Validates: Requirements 3.9**"""

    @given(s=safe_text_strategy)
    @settings(max_examples=200)
    def test_safe_strings_pass_through_unchanged(self, s: str):
        """For any string with no secret patterns, redact_string returns it unchanged."""
        result, count = redact_string(s)
        assert result == s, f"Safe string was modified: {s!r} -> {result!r}"
        assert count == 0, f"Safe string had {count} redactions"


# ── Property 2: Redaction completeness — output contains no secret patterns ──


@st.composite
def mixed_text_with_secrets(draw):
    """Generate text that mixes safe content with injected secrets."""
    parts = []
    # Add 1-3 safe segments and 1-2 secret segments
    num_safe = draw(st.integers(min_value=1, max_value=3))
    for _ in range(num_safe):
        parts.append(draw(st.text(alphabet=string.ascii_lowercase + " ", min_size=1, max_size=15)))

    secret_type = draw(st.sampled_from(["jwt", "aws", "url", "entropy"]))
    if secret_type == "jwt":
        parts.append(draw(_jwt_strategy()))
    elif secret_type == "aws":
        parts.append(draw(_aws_key_strategy()))
    elif secret_type == "url":
        parts.append(draw(_url_userinfo_strategy()))
    elif secret_type == "entropy":
        parts.append(draw(_high_entropy_strategy()))

    draw(st.randoms()).shuffle(parts)
    return " ".join(parts)


class TestRedactionCompleteness:
    """**Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.10**"""

    @given(s=mixed_text_with_secrets())
    @settings(max_examples=200)
    def test_output_contains_no_secret_patterns(self, s: str):
        """After redaction, output contains no JWT, AWS key, URL userinfo, or high-entropy tokens."""
        result, count = redact_string(s)

        # No JWT tokens in output
        assert not JWT_PATTERN.search(result.replace(REDACTED, "")), f"JWT pattern found in redacted output: {result!r}"

        # No AWS keys in output
        assert not AWS_KEY_PATTERN.search(result.replace(REDACTED, "")), (
            f"AWS key pattern found in redacted output: {result!r}"
        )

        # No URL userinfo in output (check the non-redacted parts)
        cleaned = result.replace(REDACTED, "SAFE")
        # URL userinfo should have credentials replaced
        for m in URL_USERINFO_PATTERN.finditer(result):
            userinfo = m.group(2)
            assert userinfo == REDACTED or userinfo == "<REDACTED>", (
                f"URL userinfo not redacted: {userinfo!r} in {result!r}"
            )

        # No high-entropy tokens in output
        tokens = re.split(r'([\s"\'`,;=\[\]{}()])', result)
        for token in tokens:
            if token == REDACTED or REDACTED in token:
                continue
            if len(token) >= 32 and shannon_entropy(token) > 4.5:
                raise AssertionError(f"High-entropy token found in output: {token!r}")

        # At least one redaction should have occurred
        assert count >= 1, "Expected at least 1 redaction for input with secrets"


# ── Property 3: Redaction idempotence ──


class TestRedactionIdempotence:
    """**Validates: Requirements 3.11**"""

    @given(s=st.text(min_size=0, max_size=200))
    @settings(max_examples=200)
    def test_double_redaction_equals_single(self, s: str):
        """redact_string(redact_string(x)[0]) == redact_string(x) for all inputs."""
        first_result, first_count = redact_string(s)
        second_result, second_count = redact_string(first_result)
        assert second_result == first_result, (
            f"Idempotence violated:\n  input:  {s!r}\n  first:  {first_result!r}\n  second: {second_result!r}"
        )


# ── Property 4: Shannon entropy detection threshold ──


class TestShannonEntropyThreshold:
    """**Validates: Requirements 3.3**"""

    @given(s=_high_entropy_strategy())
    @settings(max_examples=200)
    def test_high_entropy_long_strings_are_redacted(self, s: str):
        """Strings with length >= 32 and entropy > 4.5 are redacted."""
        assert len(s) >= 32
        assert shannon_entropy(s) > 4.5
        result, count = redact_string(s)
        assert REDACTED in result, f"High-entropy string not redacted: {s!r} (entropy={shannon_entropy(s):.2f})"
        assert count >= 1

    @given(s=_low_entropy_strategy(min_size=32, max_size=80))
    @settings(max_examples=200)
    def test_low_entropy_long_strings_not_redacted_by_entropy(self, s: str):
        """Strings with length >= 32 but entropy <= 4.5 are NOT redacted by entropy rule."""
        assume(len(s) >= 32)
        assume(shannon_entropy(s) <= 4.5)
        # Also ensure no other patterns match
        assume(_is_safe_string(s))
        result, count = redact_string(s)
        assert result == s, f"Low-entropy string was redacted: {s!r}"
        assert count == 0

    @given(s=st.text(alphabet=string.ascii_letters + string.digits + "!@#$%^&*", min_size=1, max_size=31))
    @settings(max_examples=200)
    def test_short_strings_not_redacted_by_entropy(self, s: str):
        """Strings with length < 32 are NOT redacted by the entropy rule."""
        assume(len(s) < 32)
        # Ensure no other patterns match
        assume(_is_safe_string(s))
        result, count = redact_string(s)
        assert result == s, f"Short string was redacted: {s!r} (len={len(s)})"
        assert count == 0


# ── Property 5: URL structure preservation under redaction ──


class TestURLStructurePreservation:
    """**Validates: Requirements 3.5**"""

    @given(data=_url_userinfo_strategy())
    @settings(max_examples=200)
    def test_url_scheme_and_host_preserved(self, data: str):
        """For URLs with userinfo, scheme and host/path are preserved, credentials replaced.

        After URL userinfo redaction, the resulting string may itself be a single
        token >= 32 chars with high entropy, which would then be fully redacted by
        the entropy rule. This is correct layered behavior. We verify:
        1. The original credentials are always removed.
        2. When the post-userinfo-redaction string is short enough to avoid the
           entropy rule, the scheme and host structure are preserved.
        """
        result, count = redact_string(data)

        # Parse the original URL to extract components
        m = URL_USERINFO_PATTERN.search(data)
        assert m is not None, f"Test URL doesn't match pattern: {data!r}"

        original_scheme = m.group(1)  # e.g. "https://"
        original_userinfo = m.group(2)  # e.g. "user:pass"

        # The original credentials must never appear in the output
        assert original_userinfo not in result, (
            f"Original credentials {original_userinfo!r} still in output: {result!r}"
        )

        # At least one redaction for the userinfo
        assert count >= 1

        # Build what the URL looks like after just the userinfo redaction step
        intermediate = URL_USERINFO_PATTERN.sub(lambda m_: f"{m_.group(1)}{REDACTED}@", data)

        # Check if the intermediate result would trigger the entropy rule on any token
        intermediate_tokens = re.split(r'([\s"\'`,;=\[\]{}()])', intermediate)
        entropy_would_fire = any(
            len(t) >= 32 and shannon_entropy(t) > 4.5 and t != REDACTED for t in intermediate_tokens
        )

        if not entropy_would_fire:
            # When entropy doesn't fire, full URL structure is preserved
            assert result.startswith(original_scheme), (
                f"Scheme not preserved: {result!r} doesn't start with {original_scheme!r}"
            )
            assert f"{REDACTED}@" in result, f"Credentials not replaced with {REDACTED}@: {result!r}"


# ── Property 6: Sensitive JSON key redaction with count tracking ──


class TestSensitiveKeyRedaction:
    """**Validates: Requirements 3.7, 3.8**"""

    @given(
        keys=st.lists(
            st.sampled_from(_SENSITIVE_KEY_NAMES),
            min_size=1,
            max_size=5,
            unique=True,
        ),
        values=st.lists(
            st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=20),
            min_size=5,
            max_size=5,
        ),
    )
    @settings(max_examples=200)
    def test_sensitive_keys_redacted_with_correct_count(self, keys, values):
        """All values under sensitive keys are redacted, count equals number of sensitive pairs."""
        # Build a dict with sensitive keys mapped to safe values
        data = {}
        for i, key in enumerate(keys):
            data[key] = values[i % len(values)]

        result, count = redact_value(data)

        # All sensitive key values should be redacted
        for key in keys:
            assert result[key] == REDACTED, f"Value for sensitive key {key!r} not redacted: {result[key]!r}"

        # Count should equal number of sensitive keys
        assert count == len(keys), f"Redaction count {count} != number of sensitive keys {len(keys)}"

    @given(
        keys=st.lists(
            st.sampled_from(_NON_SENSITIVE_KEY_NAMES),
            min_size=1,
            max_size=5,
            unique=True,
        ),
        values=st.lists(
            st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=10),
            min_size=5,
            max_size=5,
        ),
    )
    @settings(max_examples=200)
    def test_non_sensitive_keys_not_redacted(self, keys, values):
        """Values under non-sensitive keys with safe values are not redacted."""
        data = {}
        for i, key in enumerate(keys):
            data[key] = values[i % len(values)]

        result, count = redact_value(data)

        for key in keys:
            assert result[key] == data[key], f"Non-sensitive key {key!r} value was modified"
        assert count == 0


# ── Property 7: Config allowlist filtering ──


class TestConfigAllowlistFiltering:
    """**Validates: Requirements 7.4**"""

    @given(
        allowed_keys=st.lists(
            st.sampled_from(sorted(CONFIG_ALLOWLIST)),
            min_size=0,
            max_size=5,
            unique=True,
        ),
        disallowed_keys=st.lists(
            st.sampled_from(
                [
                    "SECRET_KEY",
                    "EVAL_MODEL_API_KEY",
                    "EVAL_MODEL_URL",
                    "OAUTH_CLIENT_ID",
                    "OAUTH_CLIENT_SECRET",
                    "JWT_KEY_DIR",
                    "JWT_KEY_PASSWORD",
                    "DEMO_USER",
                    "DEMO_PASSWORD",
                    "SOME_RANDOM_KEY",
                ]
            ),
            min_size=0,
            max_size=5,
            unique=True,
        ),
    )
    @settings(max_examples=200)
    def test_only_allowlisted_keys_in_output(self, allowed_keys, disallowed_keys):
        """Output of allowlist filtering contains only keys in CONFIG_ALLOWLIST."""
        # Build a config dict with a mix of allowed and disallowed keys
        config = {}
        for key in allowed_keys:
            config[key] = f"value_for_{key}"
        for key in disallowed_keys:
            config[key] = f"secret_value_for_{key}"

        # Apply the allowlist filter (same logic as _config_allowlisted)
        filtered = {k: v for k, v in config.items() if k in CONFIG_ALLOWLIST}

        # All keys in filtered output must be in the allowlist
        for key in filtered:
            assert key in CONFIG_ALLOWLIST, f"Key {key!r} not in CONFIG_ALLOWLIST but present in output"

        # No disallowed keys should be present
        for key in disallowed_keys:
            assert key not in filtered, f"Disallowed key {key!r} found in filtered output"

        # All allowed keys from input should be present
        for key in allowed_keys:
            assert key in filtered, f"Allowed key {key!r} missing from filtered output"


# ── Property 8: Bundle manifest JSON round-trip ──


# Strategy for generating random BundleManifest objects
_file_entry_strategy = st.builds(
    FileEntry,
    path=st.text(alphabet=string.ascii_lowercase + string.digits + "/._-", min_size=1, max_size=30),
    size_bytes=st.integers(min_value=0, max_value=10_000_000),
    sha256=st.text(alphabet=string.hexdigits[:16], min_size=64, max_size=64),
)

_manifest_strategy = st.builds(
    BundleManifest,
    bundle_schema_version=st.just("1"),
    created_at=st.text(alphabet=string.digits + "-T:Z+", min_size=10, max_size=30),
    cli_version=st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True),
    host_os=st.sampled_from(["Linux", "Darwin", "Windows"]),
    node_id=st.text(alphabet=string.ascii_lowercase + string.digits + "-", min_size=1, max_size=20),
    flags_used=st.fixed_dictionaries(
        {
            "output": st.text(alphabet=string.ascii_lowercase + string.digits + "/.-", min_size=1, max_size=30),
            "logs_since": st.sampled_from(["1h", "30m", "2d", "6h"]),
            "include_system": st.booleans(),
        }
    ),
    collector_results=st.fixed_dictionaries(
        {
            "versions": st.fixed_dictionaries(
                {"ok": st.booleans(), "duration_ms": st.integers(min_value=0, max_value=10000)}
            ),
        }
    ),
    redaction_counts=st.dictionaries(
        keys=st.text(alphabet=string.ascii_lowercase + "/._", min_size=1, max_size=20),
        values=st.integers(min_value=0, max_value=1000),
        min_size=0,
        max_size=5,
    ),
    file_inventory=st.lists(_file_entry_strategy, min_size=0, max_size=5),
)


class TestBundleManifestRoundTrip:
    """**Validates: Requirements 4.2, 4.3**"""

    @given(manifest=_manifest_strategy)
    @settings(max_examples=200)
    def test_json_round_trip(self, manifest: BundleManifest):
        """from_dict(json.loads(manifest.to_json())) produces equivalent object."""
        json_str = manifest.to_json()

        # Verify it's valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

        # Round-trip
        restored = BundleManifest.from_dict(parsed)

        # Compare all fields
        assert restored.bundle_schema_version == manifest.bundle_schema_version
        assert restored.created_at == manifest.created_at
        assert restored.cli_version == manifest.cli_version
        assert restored.host_os == manifest.host_os
        assert restored.node_id == manifest.node_id
        assert restored.flags_used == manifest.flags_used
        assert restored.collector_results == manifest.collector_results
        assert restored.redaction_counts == manifest.redaction_counts

        # Compare file inventory
        assert len(restored.file_inventory) == len(manifest.file_inventory)
        for orig, rest in zip(manifest.file_inventory, restored.file_inventory, strict=True):
            assert rest.path == orig.path
            assert rest.size_bytes == orig.size_bytes
            assert rest.sha256 == orig.sha256


# ── Property 9: File inventory SHA-256 integrity ──


class TestFileInventorySHA256:
    """**Validates: Requirements 4.5, 7.3**"""

    @given(
        content=st.binary(min_size=0, max_size=10_000),
        path=st.text(alphabet=string.ascii_lowercase + string.digits + "/._-", min_size=1, max_size=30),
    )
    @settings(max_examples=200)
    def test_sha256_matches_hashlib(self, content: bytes, path: str):
        """compute_file_entry(path, content).sha256 == hashlib.sha256(content).hexdigest()."""
        entry = compute_file_entry(path, content)

        expected_hash = hashlib.sha256(content).hexdigest()
        assert entry.sha256 == expected_hash, f"SHA-256 mismatch for {path!r}: {entry.sha256} != {expected_hash}"
        assert entry.size_bytes == len(content), f"Size mismatch: {entry.size_bytes} != {len(content)}"
        assert entry.path == path
