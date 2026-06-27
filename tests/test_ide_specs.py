# SPDX-FileCopyrightText: 2026 Riya Rani <rr1182764@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for observal_cli/ide_specs/cursor_hooks_spec.py

Covers all acceptance criteria from GitHub issue #835:
  - Spec returns dict in Cursor's expected schema.
  - Version constant present and tested.
  - is_observal_hook_entry() recognises both new and legacy command paths.
  - At least 4 unit tests.
  - (make lint / make test via pytest)
"""

from __future__ import annotations

import os
import sys

from observal_cli.ide_specs.cursor_hooks_spec import (
    _HOOK_EVENTS,
    _OBSERVAL_HOOK_COMMAND,
    _OBSERVAL_HOOK_COMMAND_LEGACY,
    _OBSERVAL_MATCHER_GROUP,
    CURSOR_HOOKS_SPEC_VERSION,
    build_cursor_hooks,
    get_desired_hooks,
    is_observal_hook_entry,
    is_observal_matcher_group,
)

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so we can import the module whether
# running from the repo root, the tests/ directory, or via pytest discovery.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ===========================================================================
# 1. Version constant
# ===========================================================================


class TestVersionConstant:
    """AC: Version constant present and tested."""

    def test_version_constant_exists(self):
        """CURSOR_HOOKS_SPEC_VERSION must be importable and non-empty."""
        assert CURSOR_HOOKS_SPEC_VERSION, "Version constant must not be empty"

    def test_version_constant_is_string(self):
        assert isinstance(CURSOR_HOOKS_SPEC_VERSION, str)

    def test_version_constant_semver_format(self):
        """Version should follow MAJOR.MINOR.PATCH semver."""
        parts = CURSOR_HOOKS_SPEC_VERSION.split(".")
        assert len(parts) == 3, f"Expected semver x.y.z, got: {CURSOR_HOOKS_SPEC_VERSION}"
        assert all(p.isdigit() for p in parts), "All semver parts must be numeric"


# ===========================================================================
# 2. get_desired_hooks / build_cursor_hooks schema
# ===========================================================================


class TestGetDesiredHooks:
    """AC: Spec returns dict in Cursor's expected schema."""

    def test_returns_dict(self):
        result = get_desired_hooks()
        assert isinstance(result, dict)

    def test_contains_all_four_events(self):
        """All four required lifecycle events must be present as keys."""
        result = get_desired_hooks()
        for event in ("UserPromptSubmit", "Stop", "PreToolUse", "PostToolUse"):
            assert event in result, f"Missing event key: {event}"

    def test_each_event_value_is_list(self):
        result = get_desired_hooks()
        for event, entries in result.items():
            assert isinstance(entries, list), f"Value for {event!r} must be a list"
            assert len(entries) >= 1, f"Must have ≥1 hook entry for {event!r}"

    def test_hook_entry_has_matcher_field(self):
        result = get_desired_hooks()
        for event, entries in result.items():
            for entry in entries:
                assert "matcher" in entry, f"Hook entry for {event!r} missing 'matcher'"

    def test_hook_entry_matcher_is_observal(self):
        result = get_desired_hooks()
        for event, entries in result.items():
            for entry in entries:
                assert entry["matcher"].lower() == _OBSERVAL_MATCHER_GROUP.lower()

    def test_hook_entry_has_hooks_list(self):
        result = get_desired_hooks()
        for event, entries in result.items():
            for entry in entries:
                assert "hooks" in entry
                assert isinstance(entry["hooks"], list)
                assert len(entry["hooks"]) >= 1

    def test_inner_hook_has_type_command(self):
        result = get_desired_hooks()
        for event, entries in result.items():
            for entry in entries:
                for inner in entry["hooks"]:
                    assert inner.get("type") == "command"

    def test_inner_hook_has_correct_command(self):
        result = get_desired_hooks()
        for event, entries in result.items():
            for entry in entries:
                for inner in entry["hooks"]:
                    assert inner.get("command") == _OBSERVAL_HOOK_COMMAND

    def test_build_cursor_hooks_is_alias(self):
        """build_cursor_hooks() must return the same structure as get_desired_hooks()."""
        assert build_cursor_hooks() == get_desired_hooks()

    def test_hook_events_count(self):
        """Exactly four distinct event keys."""
        result = get_desired_hooks()
        assert len(result) == 4


# ===========================================================================
# 3. is_observal_hook_entry
# ===========================================================================


class TestIsObservalHookEntry:
    """AC: is_observal_hook_entry() recognises both new and legacy command paths."""

    # --- Positive cases (canonical) ---

    def test_recognises_canonical_matcher(self):
        entry = {"matcher": "observal", "hooks": []}
        assert is_observal_hook_entry(entry) is True

    def test_recognises_canonical_matcher_case_insensitive(self):
        entry = {"matcher": "Observal", "hooks": []}
        assert is_observal_hook_entry(entry) is True

    def test_recognises_new_command_path(self):
        entry = {
            "matcher": "",
            "hooks": [{"type": "command", "command": _OBSERVAL_HOOK_COMMAND}],
        }
        assert is_observal_hook_entry(entry) is True

    def test_recognises_legacy_command_path(self):
        """Must detect pre-#829 legacy module path."""
        entry = {
            "matcher": "",
            "hooks": [{"type": "command", "command": _OBSERVAL_HOOK_COMMAND_LEGACY}],
        }
        assert is_observal_hook_entry(entry) is True

    def test_recognises_flat_command_format(self):
        """Cursor compact format: {command: ...} without nested hooks list."""
        entry = {"command": _OBSERVAL_HOOK_COMMAND}
        assert is_observal_hook_entry(entry) is True

    def test_recognises_flat_legacy_command_format(self):
        entry = {"command": _OBSERVAL_HOOK_COMMAND_LEGACY}
        assert is_observal_hook_entry(entry) is True

    def test_entry_from_get_desired_hooks_is_recognised(self):
        """Every entry produced by get_desired_hooks must be self-recognising."""
        result = get_desired_hooks()
        for event, entries in result.items():
            for entry in entries:
                assert is_observal_hook_entry(entry) is True, f"get_desired_hooks() entry for {event!r} not recognised"

    # --- Negative cases ---

    def test_rejects_foreign_matcher(self):
        entry = {"matcher": "some-other-tool", "hooks": []}
        assert is_observal_hook_entry(entry) is False

    def test_rejects_foreign_command(self):
        entry = {"hooks": [{"type": "command", "command": "python -m my.other.module"}]}
        assert is_observal_hook_entry(entry) is False

    def test_rejects_empty_dict(self):
        assert is_observal_hook_entry({}) is False

    def test_rejects_non_dict(self):
        assert is_observal_hook_entry("not a dict") is False  # type: ignore[arg-type]
        assert is_observal_hook_entry(None) is False  # type: ignore[arg-type]
        assert is_observal_hook_entry(42) is False  # type: ignore[arg-type]


# ===========================================================================
# 4. is_observal_matcher_group
# ===========================================================================


class TestIsObservalMatcherGroup:
    """Unit tests for the matcher-group helper."""

    def test_returns_true_for_observal_matcher(self):
        assert is_observal_matcher_group({"matcher": "observal"}) is True

    def test_case_insensitive(self):
        assert is_observal_matcher_group({"matcher": "OBSERVAL"}) is True
        assert is_observal_matcher_group({"matcher": "Observal"}) is True

    def test_returns_false_for_other_matcher(self):
        assert is_observal_matcher_group({"matcher": "github-copilot"}) is False

    def test_returns_false_when_matcher_missing(self):
        assert is_observal_matcher_group({"hooks": []}) is False

    def test_returns_false_for_non_dict(self):
        assert is_observal_matcher_group("observal") is False  # type: ignore[arg-type]
        assert is_observal_matcher_group(None) is False  # type: ignore[arg-type]


# ===========================================================================
# 5. Integration: round-trip sanity
# ===========================================================================


class TestRoundTrip:
    """End-to-end: build hooks, then verify detection helpers agree."""

    def test_all_generated_entries_detected_as_observal(self):
        hooks = get_desired_hooks()
        for event, entries in hooks.items():
            for entry in entries:
                assert is_observal_hook_entry(entry), (
                    f"Round-trip failure: entry for {event!r} not detected as Observal"
                )
                assert is_observal_matcher_group(entry), (
                    f"Round-trip failure: entry for {event!r} matcher group not detected"
                )

    def test_hook_events_match_module_constant(self):
        hooks = get_desired_hooks()
        assert set(hooks.keys()) == set(_HOOK_EVENTS)

    def test_no_duplicate_event_keys(self):
        hooks = get_desired_hooks()
        assert len(hooks) == len(set(hooks.keys()))
