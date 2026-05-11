# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for component_version_extras validation logic."""

import pytest
from fastapi import HTTPException

from services.component_version_extras import validate_and_extract

# ---------------------------------------------------------------------------
# Existing behaviour (should still pass)
# ---------------------------------------------------------------------------


def test_valid_hook_extra_passes():
    result = validate_and_extract("hook", {"event": "file_save", "handler_type": "python"})
    assert result["event"] == "file_save"
    assert result["handler_type"] == "python"


def test_unknown_component_type_raises_422():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("unknown_type", {})
    assert exc_info.value.status_code == 422
    assert "Unknown component type" in exc_info.value.detail


def test_unknown_fields_raises_422():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("hook", {"event": "file_save", "handler_type": "python", "bad_field": "x"})
    assert exc_info.value.status_code == 422
    assert "Unknown fields" in exc_info.value.detail


def test_missing_required_fields_raises_422():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("hook", {"priority": 5})
    assert exc_info.value.status_code == 422
    assert "Missing required fields" in exc_info.value.detail


def test_mcp_no_required_fields_passes():
    result = validate_and_extract("mcp", {"source_url": "https://example.com"})
    assert result["source_url"] == "https://example.com"


def test_empty_extra_with_no_required_fields_passes():
    result = validate_and_extract("mcp", {})
    assert result == {}


def test_none_extra_with_no_required_fields_passes():
    result = validate_and_extract("mcp", None)
    assert result == {}


# ---------------------------------------------------------------------------
# Fix 2: Required fields reject empty string and None
# ---------------------------------------------------------------------------


def test_required_field_with_empty_string_raises_422():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("hook", {"event": "", "handler_type": "python"})
    assert exc_info.value.status_code == 422
    assert "cannot be empty" in exc_info.value.detail
    assert "event" in exc_info.value.detail


def test_required_field_with_none_raises_422():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("hook", {"event": None, "handler_type": "python"})
    assert exc_info.value.status_code == 422
    assert "cannot be empty" in exc_info.value.detail
    assert "event" in exc_info.value.detail


def test_required_field_with_none_handler_type_raises_422():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("hook", {"event": "file_save", "handler_type": None})
    assert exc_info.value.status_code == 422
    assert "cannot be empty" in exc_info.value.detail
    assert "handler_type" in exc_info.value.detail


def test_required_field_prompt_category_empty_raises_422():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("prompt", {"category": "", "template": "some template"})
    assert exc_info.value.status_code == 422
    assert "cannot be empty" in exc_info.value.detail


def test_required_field_skill_task_type_empty_raises_422():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("skill", {"task_type": ""})
    assert exc_info.value.status_code == 422
    assert "cannot be empty" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Fix 1: Type validation
# ---------------------------------------------------------------------------


def test_priority_must_be_int_rejects_string():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("hook", {"event": "file_save", "handler_type": "python", "priority": "abc"})
    assert exc_info.value.status_code == 422
    assert "priority" in exc_info.value.detail
    assert "integer" in exc_info.value.detail.lower()


def test_priority_must_be_int_rejects_float():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("hook", {"event": "file_save", "handler_type": "python", "priority": 1.5})
    assert exc_info.value.status_code == 422
    assert "priority" in exc_info.value.detail


def test_priority_int_passes():
    result = validate_and_extract("hook", {"event": "file_save", "handler_type": "python", "priority": 10})
    assert result["priority"] == 10


def test_handler_config_must_be_dict_rejects_string():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract(
            "hook",
            {"event": "file_save", "handler_type": "python", "handler_config": "not a dict"},
        )
    assert exc_info.value.status_code == 422
    assert "handler_config" in exc_info.value.detail
    assert "dict" in exc_info.value.detail.lower()


def test_handler_config_dict_passes():
    result = validate_and_extract(
        "hook",
        {"event": "file_save", "handler_type": "python", "handler_config": {"key": "value"}},
    )
    assert result["handler_config"] == {"key": "value"}


def test_tool_filter_must_be_list_rejects_string():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract(
            "hook",
            {"event": "file_save", "handler_type": "python", "tool_filter": "not a list"},
        )
    assert exc_info.value.status_code == 422
    assert "tool_filter" in exc_info.value.detail
    assert "list" in exc_info.value.detail.lower()


def test_tool_filter_list_passes():
    result = validate_and_extract(
        "hook",
        {"event": "file_save", "handler_type": "python", "tool_filter": ["tool_a", "tool_b"]},
    )
    assert result["tool_filter"] == ["tool_a", "tool_b"]


def test_has_scripts_must_be_bool_rejects_string():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("skill", {"task_type": "generic", "has_scripts": "yes"})
    assert exc_info.value.status_code == 422
    assert "has_scripts" in exc_info.value.detail
    assert "bool" in exc_info.value.detail.lower()


def test_has_scripts_bool_passes():
    result = validate_and_extract("skill", {"task_type": "generic", "has_scripts": True})
    assert result["has_scripts"] is True


def test_tags_must_be_list_rejects_string():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("prompt", {"category": "coding", "template": "foo", "tags": "not a list"})
    assert exc_info.value.status_code == 422
    assert "tags" in exc_info.value.detail
    assert "list" in exc_info.value.detail.lower()


def test_tags_list_passes():
    result = validate_and_extract("prompt", {"category": "coding", "template": "foo", "tags": ["a", "b"]})
    assert result["tags"] == ["a", "b"]


def test_model_hints_must_be_dict_rejects_list():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("prompt", {"category": "coding", "template": "foo", "model_hints": ["not", "a", "dict"]})
    assert exc_info.value.status_code == 422
    assert "model_hints" in exc_info.value.detail
    assert "dict" in exc_info.value.detail.lower()


def test_event_must_be_str_rejects_int():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract("hook", {"event": 123, "handler_type": "python"})
    assert exc_info.value.status_code == 422
    assert "event" in exc_info.value.detail
    assert "str" in exc_info.value.detail.lower()


def test_file_pattern_must_be_list_rejects_string():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_extract(
            "hook",
            {"event": "file_save", "handler_type": "python", "file_pattern": "*.py"},
        )
    assert exc_info.value.status_code == 422
    assert "file_pattern" in exc_info.value.detail
    assert "list" in exc_info.value.detail.lower()


def test_file_pattern_list_passes():
    result = validate_and_extract(
        "hook",
        {"event": "file_save", "handler_type": "python", "file_pattern": ["*.py", "*.ts"]},
    )
    assert result["file_pattern"] == ["*.py", "*.ts"]
