# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for SQL LIKE wildcard escaping (SOC 2 compliance)."""

from api.sanitize import escape_like


class TestEscapeLike:
    def test_plain_string_unchanged(self):
        assert escape_like("hello") == "hello"

    def test_percent_escaped(self):
        assert escape_like("100%") == "100\\%"

    def test_underscore_escaped(self):
        assert escape_like("my_table") == "my\\_table"

    def test_backslash_escaped(self):
        assert escape_like("path\\file") == "path\\\\file"

    def test_all_wildcards_escaped(self):
        assert escape_like("%_\\") == "\\%\\_\\\\"

    def test_sqli_payload_neutralized(self):
        payload = "'; DROP TABLE users; --"
        result = escape_like(payload)
        assert "%" not in result
        assert "_" not in result.replace("\\_", "")

    def test_wildcard_flood(self):
        assert escape_like("%%%") == "\\%\\%\\%"

    def test_empty_string(self):
        assert escape_like("") == ""

    def test_unicode_preserved(self):
        assert escape_like("café_résumé") == "café\\_résumé"
