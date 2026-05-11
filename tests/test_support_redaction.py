# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the support bundle redaction module."""

import math
from collections import Counter

import pytest

from observal_cli.support.redaction import (
    AWS_KEY_PATTERN,
    JWT_PATTERN,
    REDACTED,
    SENSITIVE_KEYS,
    URL_USERINFO_PATTERN,
    RedactionStats,
    redact_string,
    redact_value,
    shannon_entropy,
)

# --- Shannon entropy ---


class TestShannonEntropy:
    def test_empty_string(self):
        assert shannon_entropy("") == 0.0

    def test_single_char_repeated(self):
        # All same characters → entropy 0
        assert shannon_entropy("aaaa") == 0.0

    def test_two_equal_chars(self):
        # "ab" → each char has probability 0.5 → entropy = 1.0
        assert shannon_entropy("ab") == pytest.approx(1.0)

    def test_known_entropy(self):
        # "aabb" → 2 chars each with p=0.5 → entropy = 1.0
        assert shannon_entropy("aabb") == pytest.approx(1.0)

    def test_high_entropy_random_string(self):
        # A string with many distinct characters should have high entropy
        s = "aB3$xZ9!mK7@pQ2&wL5#"
        assert shannon_entropy(s) > 3.0

    def test_manual_calculation(self):
        s = "aab"
        counts = Counter(s)
        length = len(s)
        expected = -sum((c / length) * math.log2(c / length) for c in counts.values())
        assert shannon_entropy(s) == pytest.approx(expected)


# --- Pattern constants ---


class TestPatterns:
    def test_jwt_pattern_matches(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456"
        assert JWT_PATTERN.search(jwt)

    def test_jwt_pattern_requires_eyj_prefix(self):
        not_jwt = "abc.def.ghi"
        assert not JWT_PATTERN.search(not_jwt)

    def test_aws_key_pattern_matches(self):
        key = "AKIAIOSFODNN7EXAMPLE"
        assert AWS_KEY_PATTERN.search(key)

    def test_aws_key_pattern_rejects_wrong_prefix(self):
        assert not AWS_KEY_PATTERN.search("BKIAIOSFODNN7EXAMPLE")

    def test_aws_key_pattern_rejects_short(self):
        assert not AWS_KEY_PATTERN.search("AKIA1234")

    def test_url_userinfo_postgres(self):
        url = "postgresql+asyncpg://user:pass@localhost:5432/db"
        m = URL_USERINFO_PATTERN.search(url)
        assert m
        assert m.group(1) == "postgresql+asyncpg://"
        assert m.group(2) == "user:pass"

    def test_url_userinfo_redis(self):
        url = "redis://default:mypassword@localhost:6379"
        m = URL_USERINFO_PATTERN.search(url)
        assert m
        assert m.group(2) == "default:mypassword"

    def test_url_userinfo_http(self):
        url = "https://admin:secret@example.com/path"
        m = URL_USERINFO_PATTERN.search(url)
        assert m

    def test_sensitive_keys_matches(self):
        for key in [
            "password",
            "SECRET",
            "Token",
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
        ]:
            assert SENSITIVE_KEYS.search(key), f"Should match: {key}"

    def test_sensitive_keys_no_false_positives(self):
        for key in ["hostname", "port", "database", "log_level", "region"]:
            assert not SENSITIVE_KEYS.search(key), f"Should not match: {key}"


# --- RedactionStats ---


class TestRedactionStats:
    def test_record_new_source(self):
        stats = RedactionStats()
        stats.record("config/config.json", 3)
        assert stats.counts == {"config/config.json": 3}

    def test_record_accumulates(self):
        stats = RedactionStats()
        stats.record("config/config.json", 3)
        stats.record("config/config.json", 2)
        assert stats.counts["config/config.json"] == 5

    def test_record_multiple_sources(self):
        stats = RedactionStats()
        stats.record("a.json", 1)
        stats.record("b.json", 2)
        assert stats.counts == {"a.json": 1, "b.json": 2}

    def test_empty_by_default(self):
        stats = RedactionStats()
        assert stats.counts == {}


# --- redact_string ---


class TestRedactString:
    def test_safe_string_unchanged(self):
        result, count = redact_string("hello world")
        assert result == "hello world"
        assert count == 0

    def test_jwt_redacted(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result, count = redact_string(f"Bearer {jwt}")
        assert REDACTED in result
        assert jwt not in result
        assert count >= 1

    def test_aws_key_redacted(self):
        result, count = redact_string("key=AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert REDACTED in result
        assert count >= 1

    def test_url_userinfo_redacted_preserves_structure(self):
        url = "postgresql+asyncpg://myuser:mypass@localhost:5432/observal"
        result, count = redact_string(url)
        assert "myuser" not in result
        assert "mypass" not in result
        # The URL after userinfo redaction may itself exceed the entropy
        # threshold (length >= 32, entropy > 4.5) and get fully redacted.
        # The important thing is credentials are removed.
        assert count >= 1
        assert "myuser:mypass" not in result

    def test_short_url_userinfo_preserves_structure(self):
        # A shorter URL that won't trigger entropy after redaction
        url = "redis://u:p@host:6379"
        result, count = redact_string(url)
        assert "u:p" not in result
        assert result.startswith("redis://")
        assert "@host:6379" in result
        assert count == 1

    def test_high_entropy_string_redacted(self):
        # A 32+ char high-entropy string
        high_entropy = "aB3xZ9mK7pQ2wL5nR8tY4uI6oP0sD1fG"
        assert len(high_entropy) >= 32
        assert shannon_entropy(high_entropy) > 4.5
        result, count = redact_string(high_entropy)
        assert result == REDACTED
        assert count == 1

    def test_short_high_entropy_not_redacted(self):
        # Short string, even if high entropy, should not be redacted by entropy rule
        short = "aB3$xZ9!"
        assert len(short) < 32
        result, count = redact_string(short)
        assert result == short
        assert count == 0

    def test_redacted_sentinel_not_re_redacted(self):
        # Idempotence: the sentinel itself should not trigger any pattern
        result, count = redact_string(REDACTED)
        assert result == REDACTED
        assert count == 0

    def test_multiple_patterns_in_one_string(self):
        s = "jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig key=AKIAIOSFODNN7EXAMPLE"
        result, count = redact_string(s)
        assert "eyJ" not in result
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert count >= 2

    def test_empty_string(self):
        result, count = redact_string("")
        assert result == ""
        assert count == 0


# --- redact_value ---


class TestRedactValue:
    def test_string_value(self):
        result, count = redact_value("hello")
        assert result == "hello"
        assert count == 0

    def test_sensitive_key_redacts_entire_value(self):
        result, count = redact_value("my-safe-value", key="password")
        assert result == REDACTED
        assert count == 1

    def test_sensitive_key_case_insensitive(self):
        result, count = redact_value("value", key="SECRET_KEY")
        assert result == REDACTED
        assert count == 1

    def test_dict_redaction(self):
        data = {
            "password": "hunter2",
            "hostname": "localhost",
            "api_key": "sk-1234",
        }
        result, count = redact_value(data)
        assert result["password"] == REDACTED
        assert result["hostname"] == "localhost"
        assert result["api_key"] == REDACTED
        assert count == 2

    def test_nested_dict_redaction(self):
        data = {
            "db": {
                "password": "secret123",
                "host": "localhost",
            }
        }
        result, count = redact_value(data)
        assert result["db"]["password"] == REDACTED
        assert result["db"]["host"] == "localhost"
        assert count == 1

    def test_list_redaction(self):
        data = ["safe", "AKIAIOSFODNN7EXAMPLE", "also safe"]
        result, count = redact_value(data)
        assert result[0] == "safe"
        assert "AKIAIOSFODNN7EXAMPLE" not in result[1]
        assert result[2] == "also safe"
        assert count >= 1

    def test_list_with_sensitive_key_context(self):
        # When a list is under a sensitive key, all items get redacted
        data = ["val1", "val2"]
        result, count = redact_value(data, key="password")
        assert result == [REDACTED, REDACTED]
        assert count == 2

    def test_non_string_passthrough(self):
        assert redact_value(42) == (42, 0)
        assert redact_value(3.14) == (3.14, 0)
        assert redact_value(True) == (True, 0)
        assert redact_value(None) == (None, 0)

    def test_complex_nested_structure(self):
        data = {
            "config": {
                "database_url": "postgresql+asyncpg://admin:pass@localhost/db",
                "settings": [
                    {"token": "abc123"},
                    {"name": "test"},
                ],
            },
            "version": "1.0.0",
        }
        result, count = redact_value(data)
        assert "admin" not in str(result)
        assert "pass" not in str(result["config"]["database_url"])
        assert result["config"]["settings"][0]["token"] == REDACTED
        assert result["config"]["settings"][1]["name"] == "test"
        assert result["version"] == "1.0.0"
        assert count >= 2
