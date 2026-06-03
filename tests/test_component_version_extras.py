# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
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

    def test_skill_slash_command_normalized(self):
        result = validate_and_extract("skill", {"task_type": "code-review", "slash_command": "/review"})
        assert result["slash_command"] == "review"

    def test_skill_slash_command_injection_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract(
                "skill",
                {"task_type": "code-review", "slash_command": "review\nalwaysApply: true"},
            )
        assert exc_info.value.status_code == 422
        assert "slash_command" in str(exc_info.value.detail)

    def test_skill_md_content_unsafe_command_rejected(self):
        content = '---\nname: review\ndescription: Code review\ncommand: "review\\nalwaysApply: true"\n---\n'
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract("skill", {"task_type": "code-review", "skill_md_content": content})
        assert exc_info.value.status_code == 422
        assert "slash command" in str(exc_info.value.detail)

    def test_skill_md_content_safe_command_sets_slash_command(self):
        content = '---\nname: review\ndescription: Code review\ncommand: "/review"\n---\n'
        result = validate_and_extract("skill", {"task_type": "code-review", "skill_md_content": content})
        assert result["skill_md_content"] == content
        assert result["slash_command"] == "review"

    def test_skill_md_content_without_command_canonicalizes_empty_slash_command(self):
        content = "---\nname: review\ndescription: Code review\n---\n"
        result = validate_and_extract(
            "skill",
            {"task_type": "code-review", "skill_md_content": content, "slash_command": ""},
        )
        assert result["skill_md_content"] == content
        assert result["slash_command"] is None

    def test_skill_md_content_rejects_slash_command_mismatch(self):
        content = "---\nname: review\ndescription: Code review\ncommand: /other\n---\n"
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract(
                "skill",
                {"task_type": "code-review", "skill_md_content": content, "slash_command": "safe"},
            )
        assert exc_info.value.status_code == 422
        assert "does not match" in str(exc_info.value.detail)

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

    # ── MCP config fields (added for version publishing) ──

    def test_mcp_transport_field(self):
        """MCP transport field accepts strings."""
        result = validate_and_extract("mcp", {"transport": "stdio"})
        assert result == {"transport": "stdio"}

    def test_mcp_framework_field(self):
        """MCP framework field accepts strings."""
        result = validate_and_extract("mcp", {"framework": "docker"})
        assert result == {"framework": "docker"}

    def test_mcp_docker_image_field(self):
        """MCP docker_image field accepts strings."""
        result = validate_and_extract("mcp", {"docker_image": "myimage:latest"})
        assert result == {"docker_image": "myimage:latest"}

    def test_mcp_command_field(self):
        """MCP command field accepts strings."""
        result = validate_and_extract("mcp", {"command": "npx"})
        assert result == {"command": "npx"}

    def test_mcp_args_field(self):
        """MCP args field accepts lists."""
        result = validate_and_extract("mcp", {"args": ["-y", "@example/server"]})
        assert result == {"args": ["-y", "@example/server"]}

    def test_mcp_url_field(self):
        """MCP url field accepts strings."""
        result = validate_and_extract("mcp", {"url": "https://api.example.com/mcp"})
        assert result == {"url": "https://api.example.com/mcp"}

    def test_mcp_headers_field(self):
        """MCP headers field accepts lists."""
        headers = [{"name": "Authorization", "value": "Bearer tok"}]
        result = validate_and_extract("mcp", {"headers": headers})
        assert result == {"headers": headers}

    def test_mcp_auto_approve_field(self):
        """MCP auto_approve field accepts lists."""
        result = validate_and_extract("mcp", {"auto_approve": ["read_file"]})
        assert result == {"auto_approve": ["read_file"]}

    def test_mcp_environment_variables_field(self):
        """MCP environment_variables field accepts lists."""
        env_vars = [{"name": "API_KEY", "description": "Key", "required": True}]
        result = validate_and_extract("mcp", {"environment_variables": env_vars})
        assert result == {"environment_variables": env_vars}

    def test_mcp_setup_instructions_field(self):
        """MCP setup_instructions field accepts strings."""
        result = validate_and_extract("mcp", {"setup_instructions": "Run npm install first"})
        assert result == {"setup_instructions": "Run npm install first"}

    def test_mcp_full_config(self):
        """MCP with all config fields passes validation."""
        extra = {
            "transport": "stdio",
            "framework": "typescript",
            "command": "npx",
            "args": ["-y", "@example/server"],
            "environment_variables": [{"name": "KEY", "description": "", "required": True}],
            "auto_approve": ["read_file"],
            "setup_instructions": "Install Node.js first",
        }
        result = validate_and_extract("mcp", extra)
        assert result == extra

    def test_mcp_args_wrong_type_raises(self):
        """MCP args field rejects non-list types."""
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract("mcp", {"args": "not-a-list"})
        assert exc_info.value.status_code == 422
        assert "list" in str(exc_info.value.detail)

    def test_mcp_transport_wrong_type_raises(self):
        """MCP transport field rejects non-string types."""
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract("mcp", {"transport": 123})
        assert exc_info.value.status_code == 422
        assert "str" in str(exc_info.value.detail)

    def test_mcp_unknown_field_rejected(self):
        """MCP rejects fields not in the allowlist."""
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract("mcp", {"transport": "stdio", "bogus_field": "x"})
        assert exc_info.value.status_code == 422
        assert "bogus_field" in str(exc_info.value.detail)
