# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for the agent YAML snapshot builder + the matching CLI behaviours.

Covers the bug where per-harness model overrides set in the web builder never
made it into the snapshot the reviewer reads, and where ``observal pull``
re-prompted for a model that the agent author had already chosen.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

# ───────────────── server-side: build_yaml_snapshot ─────────────────


def _mock_session_for_snapshot(components: list, goal: object | None = None, sections: list | None = None):
    """Build an AsyncMock session that returns the given rows in order."""
    db = AsyncMock()
    component_result = MagicMock()
    component_scalars = MagicMock()
    component_scalars.all.return_value = components
    component_result.scalars.return_value = component_scalars

    goal_result = MagicMock()
    goal_result.scalar_one_or_none.return_value = goal

    section_result = MagicMock()
    section_scalars = MagicMock()
    section_scalars.all.return_value = sections or []
    section_result.scalars.return_value = section_scalars

    side_effects = [component_result]
    if goal is not None:
        side_effects.extend([goal_result, section_result])
    else:
        side_effects.append(goal_result)
    db.execute = AsyncMock(side_effect=side_effects)
    return db


def _mock_version(*, models_by_harness: dict | None = None, supported_harnesses: list | None = None):
    ver = MagicMock()
    ver.id = uuid.uuid4()
    ver.version = "1.2.3"
    ver.description = "A helpful agent"
    ver.prompt = "be nice"
    ver.model_name = "claude-sonnet-4-5"
    ver.model_config_json = {}
    ver.models_by_harness = models_by_harness if models_by_harness is not None else {}
    ver.supported_harnesses = supported_harnesses or ["claude-code", "kiro"]
    ver.external_mcps = []
    return ver


@pytest.mark.asyncio
async def test_snapshot_includes_models_by_harness():
    """Per-harness overrides should always appear in the rendered snapshot."""
    from services.agent_snapshot import build_yaml_snapshot

    ver = _mock_version(models_by_harness={"kiro": "claude-haiku-4-5", "codex": "gpt-5"})
    db = _mock_session_for_snapshot(components=[], goal=None)

    text = await build_yaml_snapshot(ver, db)

    assert "models_by_harness" in text
    parsed = yaml.safe_load(text)
    assert parsed["models_by_harness"] == {
        "kiro": "claude-haiku-4-5",
        "codex": "gpt-5",
    }
    assert parsed["model_name"] == "claude-sonnet-4-5"
    assert parsed["version"] == "1.2.3"


@pytest.mark.asyncio
async def test_snapshot_emits_empty_dict_when_no_overrides():
    """An empty ``models_by_harness`` should be present (not omitted) so reviewers
    can tell "no overrides" apart from "data missing"."""
    from services.agent_snapshot import build_yaml_snapshot

    ver = _mock_version(models_by_harness={})
    db = _mock_session_for_snapshot(components=[], goal=None)

    text = await build_yaml_snapshot(ver, db)

    parsed = yaml.safe_load(text)
    assert "models_by_harness" in parsed
    assert parsed["models_by_harness"] == {}


@pytest.mark.asyncio
async def test_snapshot_drops_blank_overrides():
    """Empty/None override values should be filtered out."""
    from services.agent_snapshot import build_yaml_snapshot

    ver = _mock_version(models_by_harness={"kiro": "", "codex": "gpt-5"})
    db = _mock_session_for_snapshot(components=[], goal=None)

    text = await build_yaml_snapshot(ver, db)
    parsed = yaml.safe_load(text)
    assert parsed["models_by_harness"] == {"codex": "gpt-5"}


@pytest.mark.asyncio
async def test_snapshot_handles_non_dict_models_by_harness():
    """A non-dict ``models_by_harness`` (legacy data) should not crash."""
    from services.agent_snapshot import build_yaml_snapshot

    ver = _mock_version()
    ver.models_by_harness = "garbage-value"  # simulates broken legacy data
    db = _mock_session_for_snapshot(components=[], goal=None)

    text = await build_yaml_snapshot(ver, db)
    parsed = yaml.safe_load(text)
    assert parsed["models_by_harness"] == {}


# ───────────────── CLI: agent saved model + skip prompt ─────────────────


def test_agent_saved_model_prefers_per_ide_override():
    from observal_cli.cmd_pull import _agent_saved_model

    detail = {
        "model_name": "claude-sonnet-4-5",
        "models_by_harness": {"kiro": "claude-haiku-4-5", "codex": "gpt-5"},
    }
    assert _agent_saved_model(detail, "kiro") == "claude-haiku-4-5"
    assert _agent_saved_model(detail, "codex") == "gpt-5"


def test_agent_saved_model_falls_back_to_model_name_only_for_claude_code():
    from observal_cli.cmd_pull import _agent_saved_model

    detail = {
        "model_name": "claude-sonnet-4-5",
        "models_by_harness": {},
    }
    assert _agent_saved_model(detail, "claude-code") == "claude-sonnet-4-5"
    # Other harnesses should NOT inherit model_name — they emit auto sentinel.
    assert _agent_saved_model(detail, "kiro") is None
    assert _agent_saved_model(detail, "codex") is None


def test_agent_saved_model_returns_none_when_missing():
    from observal_cli.cmd_pull import _agent_saved_model

    assert _agent_saved_model(None, "kiro") is None
    assert _agent_saved_model({}, "kiro") is None
    assert _agent_saved_model({"models_by_harness": {"kiro": "  "}}, "kiro") is None


def test_collect_install_options_skips_picker_when_agent_has_saved_model():
    """The whole point of the bug fix: per-harness overrides should bypass the prompt."""
    from observal_cli.cmd_pull import _collect_install_options

    agent_detail = {
        "model_name": "claude-sonnet-4-5",
        "models_by_harness": {"kiro": "claude-haiku-4-5"},
    }

    with (
        patch("observal_cli.prompts.select_one") as mock_picker,
        patch("sys.stdin.isatty", return_value=True),
    ):
        opts = _collect_install_options(
            "kiro",
            scope="project",
            model_default=None,
            model_overrides={},
            tools=None,
            no_prompt=False,
            agent_detail=agent_detail,
        )

    assert opts["model"] == "claude-haiku-4-5"
    # The model picker must not have run.
    for call in mock_picker.call_args_list:
        args, _ = call
        assert "Model" not in (args[0] if args else ""), f"select_one was called for model selection: {call}"


def test_collect_install_options_explicit_override_wins_over_saved():
    from observal_cli.cmd_pull import _collect_install_options

    agent_detail = {
        "model_name": "claude-sonnet-4-5",
        "models_by_harness": {"kiro": "claude-haiku-4-5"},
    }

    with patch("sys.stdin.isatty", return_value=True):
        opts = _collect_install_options(
            "kiro",
            scope="project",
            model_default="claude-opus-4-5",
            model_overrides={},
            tools=None,
            no_prompt=False,
            agent_detail=agent_detail,
        )

    assert opts["model"] == "claude-opus-4-5"


def test_collect_install_options_no_saved_no_explicit_no_tty_omits_model():
    """Non-interactive with nothing chosen: don't pass options.model so the
    server falls back to its own default."""
    from observal_cli.cmd_pull import _collect_install_options

    with patch("sys.stdin.isatty", return_value=False):
        opts = _collect_install_options(
            "kiro",
            scope="project",
            model_default=None,
            model_overrides={},
            tools=None,
            no_prompt=True,
            agent_detail=None,
        )

    assert "model" not in opts
