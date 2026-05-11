# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for component_version_extras.validate_and_extract."""

import pytest
from fastapi import HTTPException

from services.component_version_extras import validate_and_extract


class TestValidateAndExtract:
    """Test per-type field validation."""

    # ── Hook type ─────────────────────────────────────────
    def test_hook_valid_minimal(self):
        """Passes with required hook fields only."""
        result = validate_and_extract("hook", {"event": "PostToolUse", "handler_type": "shell"})
        assert result == {"event": "PostToolUse", "handler_type": "shell"}

    def test_hook_valid_full(self):
        """Passes with all allowed hook fields."""
        extra = {
            "event": "PreToolUse",
            "handler_type": "http",
            "execution_mode": "blocking",
            "priority": 50,
            "handler_config": {"url": "http://example.com"},
            "scope": "global",
        }
        result = validate_and_extract("hook", extra)
        assert result == extra

    def test_hook_missing_required(self):
        """Fails when required hook fields are missing."""
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract("hook", {"event": "PostToolUse"})  # missing handler_type
        assert exc_info.value.status_code == 422
        assert "handler_type" in str(exc_info.value.detail)

    def test_hook_unknown_field(self):
        """Fails when unknown fields are provided."""
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract("hook", {"event": "X", "handler_type": "shell", "bogus": True})
        assert exc_info.value.status_code == 422
        assert "bogus" in str(exc_info.value.detail)

    # ── Skill type ────────────────────────────────────────
    def test_skill_valid(self):
        result = validate_and_extract("skill", {"task_type": "code-review", "skill_path": "/review"})
        assert result["task_type"] == "code-review"

    def test_skill_missing_required(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract("skill", {"skill_path": "/foo"})  # missing task_type
        assert exc_info.value.status_code == 422

    # ── Prompt type ───────────────────────────────────────
    def test_prompt_valid(self):
        result = validate_and_extract("prompt", {"category": "system", "template": "You are..."})
        assert result == {"category": "system", "template": "You are..."}

    def test_prompt_missing_required(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract("prompt", {"category": "system"})  # missing template
        assert exc_info.value.status_code == 422

    # ── MCP/Sandbox (no required fields) ──────────────────
    def test_mcp_empty_extra(self):
        """MCP type with no extra is fine (no required fields)."""
        result = validate_and_extract("mcp", None)
        assert result == {}

    def test_mcp_with_source_url(self):
        result = validate_and_extract("mcp", {"source_url": "https://github.com/foo/bar"})
        assert result == {"source_url": "https://github.com/foo/bar"}

    def test_sandbox_empty(self):
        result = validate_and_extract("sandbox", None)
        assert result == {}

    # ── Unknown type ──────────────────────────────────────
    def test_unknown_type_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract("unknown_thing", {"foo": "bar"})
        assert exc_info.value.status_code == 422

    # ── Edge cases ────────────────────────────────────────
    def test_none_extra_with_required_fields_raises(self):
        """If extra is None but type requires fields, error."""
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract("hook", None)
        assert exc_info.value.status_code == 422

    def test_empty_dict_extra_with_required_fields_raises(self):
        """If extra is empty dict but type requires fields, error."""
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract("hook", {})
        assert exc_info.value.status_code == 422
