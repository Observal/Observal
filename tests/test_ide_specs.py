# SPDX-FileCopyrightText: 2026 Riya Rani <rr1182764@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for observal_cli.ide_specs.gemini_hooks_spec.

Covers:
- GEMINI_HOOKS_SPEC_VERSION constant existence and format
- build_gemini_hooks() structure and schema compliance
- is_observal_hook_entry() positive and negative classification
- Round-trip: every entry built by build_gemini_hooks() is recognised as Observal-managed
"""

from __future__ import annotations

import re

import pytest

from observal_cli.ide_specs.gemini_hooks_spec import (
    _GEMINI_HOOK_EVENTS,
    _OBSERVAL_MARKER,
    _PUSH_MODULE,
    GEMINI_HOOKS_SPEC_VERSION,
    build_gemini_hooks,
    is_observal_hook_entry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

REQUIRED_KEYS = {"name", "event", "command", "enabled"}


# ---------------------------------------------------------------------------
# 1. Version constant
# ---------------------------------------------------------------------------


class TestVersionConstant:
    def test_version_is_string(self):
        assert isinstance(GEMINI_HOOKS_SPEC_VERSION, str)

    def test_version_is_semver(self):
        assert SEMVER_RE.match(GEMINI_HOOKS_SPEC_VERSION), (
            f"GEMINI_HOOKS_SPEC_VERSION {GEMINI_HOOKS_SPEC_VERSION!r} is not semver"
        )

    def test_version_is_non_empty(self):
        assert GEMINI_HOOKS_SPEC_VERSION.strip() != ""


# ---------------------------------------------------------------------------
# 2. build_gemini_hooks() - structure
# ---------------------------------------------------------------------------


class TestBuildGeminiHooks:
    @pytest.fixture(scope="class")
    def hooks(self):
        return build_gemini_hooks()

    def test_returns_list(self, hooks):
        assert isinstance(hooks, list)

    def test_returns_nonempty_list(self, hooks):
        assert len(hooks) > 0

    def test_one_entry_per_event(self, hooks):
        assert len(hooks) == len(_GEMINI_HOOK_EVENTS)

    def test_all_entries_are_dicts(self, hooks):
        for entry in hooks:
            assert isinstance(entry, dict), f"Expected dict, got {type(entry)}"

    def test_all_required_keys_present(self, hooks):
        for entry in hooks:
            missing = REQUIRED_KEYS - entry.keys()
            assert not missing, f"Entry {entry} is missing keys: {missing}"

    def test_all_entries_enabled_by_default(self, hooks):
        for entry in hooks:
            assert entry["enabled"] is True, f"Entry {entry} should be enabled"

    def test_command_references_push_module(self, hooks):
        for entry in hooks:
            assert _PUSH_MODULE in entry["command"], f"Entry {entry} command does not reference {_PUSH_MODULE}"

    def test_command_uses_python_dash_m(self, hooks):
        for entry in hooks:
            assert entry["command"].startswith("python -m "), f"Entry {entry} command should start with 'python -m '"

    def test_names_start_with_observal_marker(self, hooks):
        for entry in hooks:
            assert entry["name"].startswith(_OBSERVAL_MARKER), (
                f"Entry name {entry['name']!r} does not start with {_OBSERVAL_MARKER!r}"
            )

    def test_events_match_known_gemini_events(self, hooks):
        hook_events = {entry["event"] for entry in hooks}
        assert hook_events == set(_GEMINI_HOOK_EVENTS)

    def test_all_event_names_are_strings(self, hooks):
        for entry in hooks:
            assert isinstance(entry["event"], str)

    def test_no_duplicate_events(self, hooks):
        events = [entry["event"] for entry in hooks]
        assert len(events) == len(set(events)), "Duplicate event entries found"

    def test_no_duplicate_names(self, hooks):
        names = [entry["name"] for entry in hooks]
        assert len(names) == len(set(names)), "Duplicate name entries found"

    def test_returns_new_list_each_call(self):
        """build_gemini_hooks() must not return a cached mutable object."""
        first = build_gemini_hooks()
        second = build_gemini_hooks()
        assert first is not second

    def test_mutation_does_not_affect_subsequent_calls(self):
        first = build_gemini_hooks()
        first.clear()
        second = build_gemini_hooks()
        assert len(second) == len(_GEMINI_HOOK_EVENTS)


# ---------------------------------------------------------------------------
# 3. is_observal_hook_entry() - classification
# ---------------------------------------------------------------------------


class TestIsObservalHookEntry:
    # --- positive cases ---------------------------------------------------

    def test_recognises_entry_built_by_build_gemini_hooks(self):
        for entry in build_gemini_hooks():
            assert is_observal_hook_entry(entry), f"Expected {entry} to be recognised as an Observal hook"

    def test_recognises_minimal_valid_entry(self):
        entry = {
            "name": f"{_OBSERVAL_MARKER}_sessionStart",
            "command": f"python -m {_PUSH_MODULE}",
        }
        assert is_observal_hook_entry(entry) is True

    # --- negative cases ---------------------------------------------------

    def test_rejects_non_observal_name(self):
        entry = {
            "name": "user_defined_hook",
            "command": f"python -m {_PUSH_MODULE}",
        }
        assert is_observal_hook_entry(entry) is False

    def test_rejects_non_observal_command(self):
        entry = {
            "name": f"{_OBSERVAL_MARKER}_sessionStart",
            "command": "python -m some.other.module",
        }
        assert is_observal_hook_entry(entry) is False

    def test_rejects_empty_dict(self):
        assert is_observal_hook_entry({}) is False

    def test_rejects_non_dict_input_list(self):
        assert is_observal_hook_entry([]) is False  # type: ignore[arg-type]

    def test_rejects_non_dict_input_string(self):
        assert is_observal_hook_entry("not a dict") is False  # type: ignore[arg-type]

    def test_rejects_non_dict_input_none(self):
        assert is_observal_hook_entry(None) is False  # type: ignore[arg-type]

    def test_rejects_entry_with_missing_name(self):
        entry = {"command": f"python -m {_PUSH_MODULE}"}
        assert is_observal_hook_entry(entry) is False

    def test_rejects_entry_with_missing_command(self):
        entry = {"name": f"{_OBSERVAL_MARKER}_sessionEnd"}
        assert is_observal_hook_entry(entry) is False

    def test_marker_must_be_prefix_not_substring(self):
        """The marker appearing in the middle of the name should not match."""
        entry = {
            "name": f"prefix_{_OBSERVAL_MARKER}_suffix",
            "command": f"python -m {_PUSH_MODULE}",
        }
        # "prefix_observal_suffix" does NOT start with "observal"
        assert is_observal_hook_entry(entry) is False


# ---------------------------------------------------------------------------
# 4. Round-trip / integration
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_all_built_hooks_are_recognised(self):
        """Every entry produced by build_gemini_hooks() must pass is_observal_hook_entry()."""
        for entry in build_gemini_hooks():
            assert is_observal_hook_entry(entry)

    def test_spec_covers_session_lifecycle_events(self):
        """Observal must hook into both sessionStart and sessionEnd."""
        events = {entry["event"] for entry in build_gemini_hooks()}
        assert "sessionStart" in events
        assert "sessionEnd" in events

    def test_spec_covers_tool_call_events(self):
        """Observal must hook into tool call start and end for span telemetry."""
        events = {entry["event"] for entry in build_gemini_hooks()}
        assert "toolCallStart" in events
        assert "toolCallEnd" in events

    def test_at_least_four_hooks(self):
        """Acceptance criterion: at least 4 hooks defined."""
        assert len(build_gemini_hooks()) >= 4
