# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Focused boundary and behavior coverage for the agent pull command."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import tomllib
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
import typer
import yaml
from typer.testing import CliRunner

import observal_cli.cmd_pull as cmd_pull

RUNNER = CliRunner()


def _agent_detail(**overrides) -> dict:
    detail = {
        "id": "agent-uuid",
        "name": "reviewer",
        "namespace": "acme",
        "slug": "reviewer",
        "version": "1.4.0",
        "mcp_links": [],
        "component_links": [],
    }
    detail.update(overrides)
    return detail


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


@pytest.fixture
def pull_app() -> typer.Typer:
    root = typer.Typer()
    agent = typer.Typer()
    cmd_pull.register_pull(agent)
    root.add_typer(agent, name="agent")
    return root


@pytest.fixture
def boundaries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    import observal_cli.audit as audit
    import observal_cli.cmd_skill as cmd_skill
    import observal_cli.layer as layer
    import observal_cli.lockfile as lockfile
    import observal_cli.model_catalog as model_catalog

    adapter = MagicMock(name="adapter")
    adapter.saved_model.return_value = None
    adapter.rewrite_hooks.side_effect = lambda content, agent_id: content
    adapter.rewrite_agent_profile.side_effect = lambda content, agent_id: content
    adapter.allow_home_agent_profile.return_value = False

    def apply_install_options(options: dict, tools: str | None) -> None:
        if tools:
            options["tools"] = tools

    adapter.apply_install_options.side_effect = apply_install_options

    resolve = MagicMock(return_value="agent-uuid")
    get = MagicMock(return_value=_agent_detail())
    post = MagicMock(return_value={"config_snippet": {"agent_profile": {"path": "agent.md", "content": "agent\n"}}})
    ensure_loaded = MagicMock()
    get_adapter = MagicMock(return_value=adapter)
    local_name = MagicMock(return_value="local-reviewer")
    read_registry = MagicMock(return_value=({}, {"harnesses": {}}))
    upsert = MagicMock()
    snapshot = MagicMock()
    emit = MagicMock()
    invalidate = MagicMock()
    git_install = MagicMock()
    direct_install = MagicMock()

    def successful_skill_install(**kwargs):
        destination = kwargs.get("dest") or tmp_path / "fallback-skill"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "SKILL.md").write_text(kwargs.get("skill_md_content") or "cloned\n")
        return destination

    git_install.side_effect = successful_skill_install
    direct_install.side_effect = successful_skill_install

    monkeypatch.setattr(cmd_pull, "spinner", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(cmd_pull, "ensure_loaded", ensure_loaded)
    monkeypatch.setattr(cmd_pull, "get_adapter", get_adapter)
    monkeypatch.setattr(cmd_pull.client, "resolve_registry_reference", resolve)
    monkeypatch.setattr(cmd_pull.client, "get", get)
    monkeypatch.setattr(cmd_pull.client, "post", post)
    monkeypatch.setattr(lockfile, "local_registry_name", local_name)
    monkeypatch.setattr(lockfile, "read_registry_lockfile", read_registry)
    monkeypatch.setattr(lockfile, "upsert_agent", upsert)
    monkeypatch.setattr(layer, "ensure_local_snapshot", snapshot)
    monkeypatch.setattr(audit, "emit_cli_audit", emit)
    monkeypatch.setattr(model_catalog, "invalidate_cache", invalidate)
    monkeypatch.setattr(cmd_skill, "install_skill_from_git", git_install)
    monkeypatch.setattr(cmd_skill, "install_skill_registry_direct", direct_install)

    return SimpleNamespace(
        adapter=adapter,
        resolve=resolve,
        get=get,
        post=post,
        ensure_loaded=ensure_loaded,
        get_adapter=get_adapter,
        local_name=local_name,
        read_registry=read_registry,
        upsert=upsert,
        snapshot=snapshot,
        emit=emit,
        invalidate=invalidate,
        git_install=git_install,
        direct_install=direct_install,
    )


def _invoke(
    app: typer.Typer,
    target: Path,
    *options: str,
    reference: str = "acme/reviewer",
    harness: str = "claude-code",
    no_prompt: bool = True,
):
    args = ["agent", "pull", reference, "--harness", harness, "--dir", str(target)]
    if no_prompt:
        args.append("--no-prompt")
    args.extend(options)
    return RUNNER.invoke(app, args)


def test_component_conflicts_report_only_other_agent_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    import observal_cli.lockfile as lockfile

    registry = {
        "harnesses": {
            "cursor": {
                "agents": [
                    {
                        "name": "incoming",
                        "components": [{"name": "shared", "version": "0.1.0"}],
                    },
                    {
                        "name": "older-agent",
                        "components": [
                            {"name": "shared", "version": "1.0.0"},
                            {"name": "unversioned", "version": None},
                        ],
                    },
                ]
            }
        }
    }
    read_registry = MagicMock(return_value=({}, registry))
    monkeypatch.setattr(lockfile, "read_registry_lockfile", read_registry)

    conflicts = cmd_pull._component_conflicts(
        "cursor",
        "incoming",
        [
            {"type": "mcp", "name": "shared", "version": "2.0.0"},
            {"name": "unversioned", "version": None},
        ],
    )

    assert conflicts == ["mcp shared: v2.0.0 (this agent) vs v1.0.0 (from older-agent)"]

    read_registry.side_effect = OSError("broken lockfile")
    with pytest.raises(typer.Exit) as error:
        cmd_pull._component_conflicts("cursor", "incoming", [])
    assert error.value.exit_code == 9


def test_resolve_hook_paths_uses_path_fallback_only_in_quoted_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    monkeypatch.setattr(Path, "is_file", lambda _path: False)
    which = MagicMock(side_effect=["/opt/observal/observal-hook.sh", None])
    monkeypatch.setattr(shutil, "which", which)
    source = (
        'command = "observal-hook.sh --agent-name reviewer"\n'
        "observal-hook.sh appears in prose\n"
        'stop = "observal-stop-hook.sh"\n'
    )

    rendered = cmd_pull._resolve_hook_paths(source)

    assert rendered == (
        'command = "/opt/observal/observal-hook.sh"\n'
        "observal-hook.sh appears in prose\n"
        'stop = "observal-stop-hook.sh"\n'
    )
    assert which.call_args_list == [call("observal-hook.sh"), call("observal-stop-hook.sh")]


def test_collect_mcp_env_vars_prompts_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    detail = {
        "mcp_links": [{"mcp_listing_id": "mcp-1", "mcp_name": "Primary"}],
        "component_links": [
            {"component_type": "mcp", "component_id": "mcp-1", "component_name": "duplicate"},
            {"component_type": "mcp", "component_id": "mcp-2", "component_name": ""},
            {"component_type": "skill", "component_id": "skill-1"},
        ],
    }

    def get(path: str):
        if path.endswith("mcp-1"):
            return {
                "environment_variables": [
                    {"name": "TOKEN", "description": "required token", "required": True},
                    {"name": "EMPTY", "description": "optional", "required": False},
                    {"name": "FILLED", "required": False},
                ]
            }
        if path.endswith("mcp-2"):
            return {
                "name": "Secondary",
                "environment_variables": [
                    {"name": "ASK", "required": True},
                    {"name": "REGION", "required": False},
                ],
            }
        return {"environment_variables": []}

    prompt = MagicMock(side_effect=["", "optional-value", "typed-secret"])
    monkeypatch.setattr(cmd_pull.client, "get", get)
    monkeypatch.setattr(cmd_pull, "password_input", prompt)

    values = cmd_pull._collect_mcp_env_vars(
        detail,
        env_overrides={"TOKEN": "flag-secret", "REGION": "eu-west-1"},
    )

    assert values == {
        "mcp-1": {"TOKEN": "flag-secret", "FILLED": "optional-value"},
        "mcp-2": {"ASK": "typed-secret", "REGION": "eu-west-1"},
    }
    assert prompt.call_args_list == [
        call("  EMPTY [dim](optional)[/dim] (press Enter to skip)"),
        call("  FILLED (press Enter to skip)"),
        call("  ASK"),
    ]
    output = capsys.readouterr().out
    assert "Primary requires 1 environment variable(s)" in output
    assert "TOKEN (from --env)" in output
    assert "Secondary: 1 optional env var(s)" in output


def test_collect_mcp_env_vars_no_prompt_uses_only_known_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = {"mcp_links": [{"mcp_listing_id": "mcp-1"}], "component_links": []}
    monkeypatch.setattr(
        cmd_pull.client,
        "get",
        lambda _path: {
            "environment_variables": [
                {"name": "REQUIRED"},
                {"name": "OPTIONAL", "required": False},
            ]
        },
    )
    prompt = MagicMock(side_effect=AssertionError("prompted in no-prompt mode"))
    monkeypatch.setattr(cmd_pull, "password_input", prompt)

    assert cmd_pull._collect_mcp_env_vars(
        detail,
        no_prompt=True,
        env_overrides={"OPTIONAL": "set", "UNKNOWN": "ignored"},
    ) == {"mcp-1": {"OPTIONAL": "set"}}
    prompt.assert_not_called()
    assert cmd_pull._collect_mcp_env_vars({}, no_prompt=True) == {}


def test_collect_mcp_headers_prompts_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    detail = {
        "mcp_links": [{"mcp_listing_id": "mcp-1", "mcp_name": "Remote"}],
        "component_links": [
            {"component_type": "mcp", "component_id": "mcp-1"},
            {"component_type": "mcp", "component_id": "mcp-2", "component_name": ""},
            {"component_type": "hook", "component_id": "hook-1"},
        ],
    }

    def get(path: str):
        if path.endswith("mcp-1"):
            return {
                "headers": [
                    {"name": "Authorization", "description": "access token"},
                    {"name": "X-Skip", "description": "optional", "required": False},
                    {"name": "X-Filled", "required": False},
                ]
            }
        if path.endswith("mcp-2"):
            return {
                "name": "Fallback name",
                "headers": [
                    {"name": "X-Required"},
                    {"name": "X-Region", "required": False},
                ],
            }
        return {"headers": []}

    prompt = MagicMock(side_effect=["", "optional-value", "required-value"])
    monkeypatch.setattr(cmd_pull.client, "get", get)
    monkeypatch.setattr(cmd_pull, "password_input", prompt)

    values = cmd_pull._collect_mcp_headers(
        detail,
        header_overrides={"Authorization": "Bearer flag", "X-Region": "eu"},
    )

    assert values == {
        "mcp-1": {"Authorization": "Bearer flag", "X-Filled": "optional-value"},
        "mcp-2": {"X-Required": "required-value", "X-Region": "eu"},
    }
    assert prompt.call_args_list == [
        call("  X-Skip [dim](optional)[/dim] (press Enter to skip)"),
        call("  X-Filled (press Enter to skip)"),
        call("  X-Required"),
    ]
    output = capsys.readouterr().out
    assert "Remote requires 1 header(s)" in output
    assert "Authorization (from --header)" in output
    assert "Fallback name: 1 optional header(s)" in output


def test_collect_mcp_headers_no_prompt_uses_only_known_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = {"mcp_links": [{"mcp_listing_id": "mcp-1"}]}
    monkeypatch.setattr(
        cmd_pull.client,
        "get",
        lambda _path: {"headers": [{"name": "Required"}, {"name": "Optional", "required": False}]},
    )
    prompt = MagicMock(side_effect=AssertionError("prompted in no-prompt mode"))
    monkeypatch.setattr(cmd_pull, "password_input", prompt)

    assert cmd_pull._collect_mcp_headers(
        detail,
        no_prompt=True,
        header_overrides={"Optional": "yes", "Unknown": "ignored"},
    ) == {"mcp-1": {"Optional": "yes"}}
    prompt.assert_not_called()
    assert cmd_pull._collect_mcp_headers({}, no_prompt=True) == {}


def test_dict_to_toml_serializes_every_supported_value_shape() -> None:
    rendered = cmd_pull._dict_to_toml(
        {
            "mcp_servers": {
                "server": {
                    "args": ["one", "two"],
                    "env": {"TOKEN": "secret"},
                    "enabled": True,
                    "label": 'quoted "value"',
                    "retries": 3,
                }
            }
        }
    )

    assert rendered == (
        "[mcp_servers.server]\n"
        'args = ["one", "two"]\n'
        'env.TOKEN = "secret"\n'
        "enabled = true\n"
        'label = "quoted \\"value\\""\n'
        "retries = 3\n"
    )


def test_write_file_handles_toml_json_strings_and_empty_content(tmp_path: Path) -> None:
    toml_path = tmp_path / "config.toml"
    assert cmd_pull._write_file(toml_path, {"mcp_servers": {"old": {"command": "old"}}}) == "created"
    assert (
        cmd_pull._write_file(
            toml_path,
            {"mcp_servers": {"new": {"command": "new"}}},
            merge_mcp=True,
        )
        == "merged"
    )
    assert toml_path.read_text() == ('[mcp_servers.old]\ncommand = "old"\n\n[mcp_servers.new]\ncommand = "new"\n')

    json_path = tmp_path / "broken.json"
    json_path.write_text("not-json")
    with pytest.raises(ValueError, match="unreadable JSON"):
        cmd_pull._write_file(json_path, {"servers": {"new": {"command": "npx"}}}, merge_mcp=True)
    assert json_path.read_text() == "not-json"

    empty_path = tmp_path / "empty.json"
    assert cmd_pull._write_file(empty_path, {}) == "created"
    assert empty_path.read_text() == "{}\n"

    text_path = tmp_path / "rules.md"
    assert cmd_pull._write_file(text_path, "first") == "created"
    assert cmd_pull._write_file(text_path, "second") == "updated"
    assert text_path.read_text() == "second"


def test_write_file_yaml_merges_or_preserves_existing_content(tmp_path: Path) -> None:
    path = tmp_path / "goose.yaml"
    path.write_text(yaml.safe_dump({"provider": "anthropic", "extensions": {"old": {"type": "stdio"}}}))
    assert (
        cmd_pull._write_file(
            path,
            {"extensions": {"github": {"type": "stdio"}}},
            merge_mcp=True,
        )
        == "merged"
    )
    assert yaml.safe_load(path.read_text()) == {
        "provider": "anthropic",
        "extensions": {"old": {"type": "stdio"}, "github": {"type": "stdio"}},
    }

    replace_path = tmp_path / "replace.yml"
    replace_path.write_text(yaml.safe_dump({"provider": "old", "extensions": {"old": {}}}))
    assert (
        cmd_pull._write_file(
            replace_path,
            {"provider": "new", "extensions": {"new": {}}},
        )
        == "merged"
    )
    assert yaml.safe_load(replace_path.read_text()) == {"provider": "new", "extensions": {"new": {}}}

    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("extensions: [unterminated\n")
    with pytest.raises(ValueError, match="unreadable YAML"):
        cmd_pull._write_file(malformed, {"extensions": {"new": {}}}, merge_mcp=True)
    assert malformed.read_text() == "extensions: [unterminated\n"

    unexpected = tmp_path / "unexpected.yaml"
    unexpected.write_text("- one\n- two\n")
    with pytest.raises(ValueError, match="top level"):
        cmd_pull._write_file(unexpected, {"extensions": {}}, merge_mcp=True)
    assert unexpected.read_text() == "- one\n- two\n"

    created = tmp_path / "new.yaml"
    assert cmd_pull._write_file(created, {"extensions": {"new": {}}}, merge_mcp=True) == "created"
    assert yaml.safe_load(created.read_text()) == {"extensions": {"new": {}}}


def test_rewrite_kiro_hooks_replaces_observal_entries_and_keeps_user_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    import observal_cli.harness_specs.kiro_hooks_spec as spec

    build = MagicMock(
        return_value={
            "stop": [{"command": "new stop"}],
            "userPromptSubmit": [{"command": "new prompt"}],
        }
    )
    monkeypatch.setattr(spec, "build_kiro_hooks", build)
    monkeypatch.setattr(cmd_pull.config, "get_or_exit", lambda: {"server_url": "https://registry.example/"})
    content = {
        "hooks": {
            "stop": [
                {"command": "python -m observal_cli.old"},
                {"command": "echo user"},
            ],
            "custom": [{"command": "custom"}],
        }
    }

    assert cmd_pull._rewrite_kiro_hooks(content, agent_id="agent-1") == {
        "hooks": {
            "stop": [{"command": "echo user"}, {"command": "new stop"}],
            "custom": [{"command": "custom"}],
            "userPromptSubmit": [{"command": "new prompt"}],
        }
    }
    build.assert_called_once_with("https://registry.example/api/v1/telemetry/hooks", agent_id="agent-1")


def test_rewrite_copilot_hooks_removes_both_legacy_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    import observal_cli.harness_specs.copilot_cli_hooks_spec as spec

    build = MagicMock(
        return_value={"hooks": {"sessionStart": [{"bash": "new attributed"}], "stop": [{"bash": "new stop"}]}}
    )
    monkeypatch.setattr(spec, "build_copilot_cli_hooks", build)
    content = {
        "hooks": {
            "sessionStart": [
                {"bash": "python -m observal_cli.hooks.copilot_cli_session_push"},
                {"bash": "python -m observal_cli.hooks.session_push --harness copilot-cli"},
                {"bash": "echo user"},
            ]
        }
    }

    assert cmd_pull._rewrite_copilot_cli_hooks(content, agent_id="agent-2") == {
        "hooks": {
            "sessionStart": [{"bash": "echo user"}, {"bash": "new attributed"}],
            "stop": [{"bash": "new stop"}],
        }
    }
    build.assert_called_once_with(agent_id="agent-2")
    empty = {}
    assert cmd_pull._rewrite_copilot_cli_hooks(empty, agent_id="ignored") is empty


def test_resolve_path_maps_project_home_and_rejects_traversal(
    tmp_path: Path, isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = (tmp_path / "project").resolve()
    target.mkdir()

    assert cmd_pull._resolve_path("rules/AGENTS.md", target) == target / "rules" / "AGENTS.md"
    assert cmd_pull._resolve_path("~/agent/config.json", target) == target / "agent" / "config.json"
    assert cmd_pull._resolve_path("~\\agent.json", target) == target / "agent.json"
    assert cmd_pull._resolve_path("~/agent/config.json", target, allow_home=True) == (
        isolated_home / "agent" / "config.json"
    )

    outside = tmp_path / "outside"
    outside.mkdir()
    (target / "link").symlink_to(outside, target_is_directory=True)
    for unsafe in ("../outside.txt", str(outside / "absolute.txt"), "link/escaped.txt"):
        with pytest.raises(typer.Exit) as caught:
            cmd_pull._resolve_path(unsafe, target)
        assert caught.value.exit_code == 7
    output = capsys.readouterr().out
    assert "escapes the target directory" in output


def test_parse_model_overrides_and_saved_model_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    assert cmd_pull._parse_model_overrides([" default-one ", "codex = gpt-5", " default-two "]) == (
        "default-two",
        {"codex": "gpt-5"},
    )
    for invalid in ("=missing", "kiro=", ""):
        with pytest.raises(typer.Exit) as error:
            cmd_pull._parse_model_overrides([invalid])
        assert error.value.exit_code == 7

    adapter = MagicMock()
    adapter.saved_model.return_value = "saved-model"
    ensure = MagicMock()
    get_adapter = MagicMock(return_value=adapter)
    monkeypatch.setattr(cmd_pull, "ensure_loaded", ensure)
    monkeypatch.setattr(cmd_pull, "get_adapter", get_adapter)
    detail = {"models_by_harness": {"kiro": "saved-model"}}

    assert cmd_pull._agent_saved_model(detail, "kiro") == "saved-model"
    ensure.assert_called_once_with()
    get_adapter.assert_called_once_with("kiro")
    adapter.saved_model.assert_called_once_with(detail)


def test_collect_install_options_interactively_selects_scope_model_and_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    import observal_cli.model_catalog as catalog
    import observal_shared.harness_registry as registry

    adapter = MagicMock()
    monkeypatch.setattr(cmd_pull, "_SCOPE_AWARE_HARNESSES", {"demo": ("project files", "user files")})
    monkeypatch.setattr(registry, "get_default_scope", lambda _harness: "user")
    monkeypatch.setattr(registry, "has_model_selection", lambda _harness: True)
    monkeypatch.setattr(cmd_pull, "_agent_saved_model", lambda _detail, _harness: None)
    monkeypatch.setattr(cmd_pull, "ensure_loaded", MagicMock())
    monkeypatch.setattr(cmd_pull, "get_adapter", lambda _harness: adapter)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    picker = MagicMock(side_effect=["project files", "Pretty model"])
    monkeypatch.setattr(cmd_pull, "select_one", picker)
    fetch = MagicMock(return_value={"models": [{"id": "model-1"}]})
    choices = MagicMock(return_value=[("Pretty model", "provider/model-1")])
    monkeypatch.setattr(catalog, "fetch_catalog", fetch)
    monkeypatch.setattr(catalog, "model_choices_for_picker", choices)

    options = cmd_pull._collect_install_options(
        "demo",
        scope=None,
        model_default=None,
        model_overrides={},
        tools="Read,Write",
        no_prompt=False,
        refresh_models=True,
        agent_detail={},
    )

    assert options == {"scope": "project", "model": "provider/model-1"}
    assert picker.call_args_list == [
        call("  Scope", ["user files", "project files"], default="user files"),
        call(
            "  Model",
            ["auto (let the harness decide)", "Pretty model"],
            default="auto (let the harness decide)",
        ),
    ]
    fetch.assert_called_once_with(refresh=True)
    choices.assert_called_once_with({"models": [{"id": "model-1"}]}, "demo")
    adapter.apply_install_options.assert_called_once_with(options, "Read,Write")


def test_collect_install_options_handles_catalog_and_model_format_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import observal_cli.model_catalog as catalog
    import observal_cli.render as render
    import observal_shared.harness_registry as registry

    adapter = MagicMock()
    monkeypatch.setattr(cmd_pull, "_SCOPE_AWARE_HARNESSES", {})
    monkeypatch.setattr(registry, "has_model_selection", lambda _harness: True)
    monkeypatch.setattr(cmd_pull, "ensure_loaded", MagicMock())
    monkeypatch.setattr(cmd_pull, "get_adapter", lambda _harness: adapter)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    monkeypatch.setattr(cmd_pull, "_agent_saved_model", lambda _detail, _harness: "saved/model")
    format_model = MagicMock(return_value=("Pretty saved", "", {}))
    monkeypatch.setattr(render, "format_model", format_model)
    assert cmd_pull._collect_install_options(
        "demo",
        scope=None,
        model_default=None,
        model_overrides={},
        tools=None,
        no_prompt=False,
    ) == {"model": "saved/model"}
    assert "Pretty saved (from agent)" in capsys.readouterr().out

    format_model.side_effect = ValueError("bad model")
    assert cmd_pull._collect_install_options(
        "demo",
        scope=None,
        model_default=None,
        model_overrides={},
        tools=None,
        no_prompt=False,
    ) == {"model": "saved/model"}
    assert "saved/model (from agent)" in capsys.readouterr().out

    monkeypatch.setattr(cmd_pull, "_agent_saved_model", lambda _detail, _harness: None)
    monkeypatch.setattr(catalog, "fetch_catalog", MagicMock(side_effect=RuntimeError("offline")))
    choices = MagicMock(return_value=[])
    monkeypatch.setattr(catalog, "model_choices_for_picker", choices)
    monkeypatch.setattr(cmd_pull, "select_one", lambda *_args, **_kwargs: "auto (let the harness decide)")
    with pytest.raises(RuntimeError, match="offline"):
        cmd_pull._collect_install_options(
            "demo",
            scope=None,
            model_default=None,
            model_overrides={},
            tools=None,
            no_prompt=False,
        )
    choices.assert_not_called()


def test_collect_install_options_no_prompt_uses_registry_default_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    import observal_shared.harness_registry as registry

    adapter = MagicMock()
    monkeypatch.setattr(cmd_pull, "_SCOPE_AWARE_HARNESSES", {"demo": ("project", "user")})
    monkeypatch.setattr(registry, "get_default_scope", lambda _harness: "user")
    monkeypatch.setattr(registry, "has_model_selection", lambda _harness: False)
    monkeypatch.setattr(cmd_pull, "ensure_loaded", MagicMock())
    monkeypatch.setattr(cmd_pull, "get_adapter", lambda _harness: adapter)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    picker = MagicMock(side_effect=AssertionError("no prompt expected"))
    monkeypatch.setattr(cmd_pull, "select_one", picker)

    assert cmd_pull._collect_install_options(
        "demo",
        scope=None,
        model_default=None,
        model_overrides={},
        tools=None,
        no_prompt=True,
    ) == {"scope": "user"}
    picker.assert_not_called()


def test_pull_full_project_flow_writes_every_shape_and_exact_side_effects(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "project"
    target.mkdir()
    detail = _agent_detail(
        mcp_links=[{"mcp_listing_id": "mcp-1", "mcp_name": "GitHub"}],
        component_links=[
            {
                "component_type": "mcp",
                "component_id": "mcp-1",
                "component_name": "github",
                "version_ref": "2.1.0",
            },
            {
                "component_type": "skill",
                "component_id": "skill-1",
                "component_name": "review-skill",
                "version_ref": "3.0.0",
            },
        ],
    )
    listing = {
        "environment_variables": [{"name": "API_KEY"}, {"name": "UNSET", "required": False}],
        "headers": [{"name": "Authorization"}, {"name": "X-Unset", "required": False}],
    }

    def get(path: str):
        if path == "/api/v1/agents/agent-uuid":
            return detail
        if path == "/api/v1/mcps/mcp-1":
            return listing
        raise AssertionError(path)

    boundaries.get.side_effect = get

    snippet = {
        "mcp_config": {
            "path": ".config/mcp.json",
            "content": {"mcpServers": {"new": {"command": "npx", "args": ["new"]}}},
        },
        "hooks_config": {
            "path": ".config/hooks.json",
            "content": {
                "hooks": {
                    "new": [{"command": "python3 -m observal_cli.hooks.session_push"}],
                }
            },
            "merge": True,
        },
        "agent_profile": {
            "path": ".agents/reviewer.json",
            "content": {"name": "reviewer", "tools": ["read"]},
        },
        "steering_file": {"path": ".agents/steering.md", "content": "steer\n"},
        "hook_files": [
            {"path": ".agents/hooks/run.sh", "content": "#!/bin/sh\nexit 0\n", "executable": True},
            {"path": ".agents/hooks/data.txt", "content": "data\n"},
        ],
        "prompt_files": [{"path": ".github/prompts/review.prompt.md", "content": "review prompt\n"}],
        "skills": [{"path": ".agents/skills/native/SKILL.md", "content": "native skill\n"}],
        "skill_components": [
            {
                "name": "git-skill",
                "path": ".agents/skills/git-skill/SKILL.md",
                "git_url": "https://example.test/skill.git",
                "skill_path": "skills/review",
                "git_ref": "v2",
                "skill_md_content": "cached git skill\n",
            },
            {
                "name": "direct-skill",
                "path": ".agents/skills/direct-skill/SKILL.md",
                "skill_md_content": "direct skill\n",
                "script_content": "print('ok')\n",
                "script_filename": "run.py",
            },
        ],
        "mcp_setup_commands": [
            ["good", "mcp", "add", "new"],
            ["missing", "mcp", "add", "manual"],
            ["bad", "mcp", "add", "broken"],
        ],
        "_warnings": ["snippet warning"],
    }
    boundaries.post.return_value = {"config_snippet": snippet, "warnings": ["server warning"]}

    mcp_path = target / ".config" / "mcp.json"
    mcp_path.parent.mkdir(parents=True)
    mcp_path.write_text(json.dumps({"mcpServers": {"old": {"command": "old"}}, "keep": True}))
    hooks_path = target / ".config" / "hooks.json"
    hooks_path.write_text(json.dumps({"hooks": {"old": [{"command": "echo user"}]}, "keep": True}))
    executable = target / ".agents" / "hooks" / "run.sh"
    executable.parent.mkdir(parents=True)
    executable.write_text("old\n")
    prompt_path = target / ".github" / "prompts" / "review.prompt.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("old prompt\n")

    def rewrite_hooks(content: dict, agent_id: str) -> dict:
        content["hooks"]["adapter"] = [{"agent_id": agent_id}]
        return content

    def rewrite_profile(content: dict, agent_id: str) -> dict:
        return {**content, "agent_id": agent_id}

    boundaries.adapter.rewrite_hooks.side_effect = rewrite_hooks
    boundaries.adapter.rewrite_agent_profile.side_effect = rewrite_profile

    run = MagicMock()

    def run_command(command: list[str], **_kwargs):
        return subprocess.CompletedProcess(command, 0, "", "")

    run.side_effect = run_command
    monkeypatch.setattr(cmd_pull.subprocess, "run", run)

    result = _invoke(
        pull_app,
        target,
        "--scope",
        "project",
        "--model",
        "fallback-model",
        "--model",
        "claude-code=selected-model",
        "--tools",
        "Read,Write",
        "--env",
        "API_KEY='secret'",
        "--header",
        'Authorization="Bearer token"',
        "--version",
        "1.4.0",
    )

    assert result.exit_code == 0, result.output
    boundaries.resolve.assert_called_once_with("agent", "acme/reviewer")
    assert boundaries.get.call_args_list == [
        call("/api/v1/agents/agent-uuid"),
        call("/api/v1/mcps/mcp-1"),
        call("/api/v1/mcps/mcp-1"),
    ]
    boundaries.local_name.assert_called_once_with(
        "claude-code",
        "agent",
        "acme",
        "reviewer",
        scope="project",
        directory=str(target.resolve()),
    )
    boundaries.post.assert_called_once_with(
        "/api/v1/agents/agent-uuid/install",
        {
            "harness": "claude-code",
            "env_values": {"mcp-1": {"API_KEY": "secret"}},
            "header_values": {"mcp-1": {"Authorization": "Bearer token"}},
            "options": {
                "scope": "project",
                "model": "selected-model",
                "tools": "Read,Write",
                "local_name": "local-reviewer",
            },
            "platform": sys.platform,
            "version": "1.4.0",
        },
    )
    boundaries.invalidate.assert_not_called()

    assert json.loads(mcp_path.read_text()) == {
        "mcpServers": {
            "old": {"command": "old"},
            "new": {"command": "npx", "args": ["new"]},
        },
        "keep": True,
    }
    assert json.loads(hooks_path.read_text()) == {
        "hooks": {
            "old": [{"command": "echo user"}],
            "new": [{"command": f"{sys.executable} -m observal_cli.hooks.session_push"}],
            "adapter": [{"agent_id": "agent-uuid"}],
        },
        "keep": True,
    }
    assert json.loads((target / ".agents" / "reviewer.json").read_text()) == {
        "name": "reviewer",
        "tools": ["read"],
        "agent_id": "agent-uuid",
    }
    assert (target / ".agents" / "steering.md").read_text() == "steer\n"
    assert executable.read_text() == "#!/bin/sh\nexit 0\n"
    assert executable.stat().st_mode & stat.S_IXUSR
    assert (target / ".agents" / "hooks" / "data.txt").read_text() == "data\n"
    assert prompt_path.read_text() == "review prompt\n"
    assert (target / ".agents" / "skills" / "native" / "SKILL.md").read_text() == "native skill\n"
    assert (target / ".agents" / "skills" / "git-skill" / "SKILL.md").read_text() == "cached git skill\n"
    assert (target / ".agents" / "skills" / "direct-skill" / "SKILL.md").read_text() == "direct skill\n"

    boundaries.git_install.assert_called_once_with(
        name="git-skill",
        git_url="https://example.test/skill.git",
        skill_path="skills/review",
        git_ref="v2",
        harness="claude-code",
        scope="project",
        skill_md_content="cached git skill\n",
        cwd=target.resolve(),
        dest=target.resolve() / ".agents" / "skills" / "git-skill",
    )
    boundaries.direct_install.assert_called_once_with(
        name="direct-skill",
        skill_md_content="direct skill\n",
        script_content="print('ok')\n",
        script_filename="run.py",
        harness="claude-code",
        scope="project",
        cwd=target.resolve(),
        dest=target.resolve() / ".agents" / "skills" / "direct-skill",
    )
    boundaries.upsert.assert_called_once_with(
        "claude-code",
        name="reviewer",
        agent_id="agent-uuid",
        version="1.4.0",
        scope="project",
        directory=str(target.resolve()),
        components=[
            {"type": "mcp", "name": "github", "id": "mcp-1", "version": "2.1.0"},
            {"type": "skill", "name": "review-skill", "id": "skill-1", "version": "3.0.0"},
        ],
        namespace="acme",
        slug="reviewer",
        local_name="local-reviewer",
    )
    boundaries.snapshot.assert_called_once_with(project_dir=str(target.resolve()))
    boundaries.adapter.persist_active_agent.assert_called_once_with("agent-uuid", "reviewer", "1.4.0")
    boundaries.emit.assert_called_once_with(
        "agent.pull",
        resource_type="agent",
        resource_id="agent-uuid",
        resource_name="reviewer",
        detail="harness=claude-code",
        sensitivity="high",
    )
    assert run.call_args_list == [
        call(["good", "mcp", "add", "new"], capture_output=True, text=True),
        call(["missing", "mcp", "add", "manual"], capture_output=True, text=True),
        call(["bad", "mcp", "add", "broken"], capture_output=True, text=True),
    ]
    for visible in (
        "Pulled claude-code config (10 files)",
        "server warning",
        "snippet warning",
        "Registered MCP servers",
    ):
        assert visible in result.output


def test_pull_dry_run_previews_all_shapes_without_mutating_boundaries(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "project"
    target.mkdir()
    boundaries.get.return_value = _agent_detail()
    boundaries.post.return_value = {
        "config_snippet": {
            "mcp_config": {"path": "mcp.json", "content": {"mcpServers": {}}},
            "hooks_config": {"path": "hooks.json", "content": {"hooks": {}}},
            "agent_profile": {"path": "agent.json", "content": {"name": "reviewer"}},
            "steering_file": {"path": "steering.md", "content": "steer"},
            "hook_files": [{"path": "hook.sh", "content": "hook", "executable": True}],
            "prompt_files": [{"path": "prompt.md", "content": "prompt"}],
            "skills": [{"path": "native/SKILL.md", "content": "skill"}],
            "skill_components": [
                {"name": "git-skill", "git_url": "https://example.test/git"},
                {"name": "direct-skill", "path": "direct/SKILL.md", "skill_md_content": "direct"},
            ],
            "mcp_setup_commands": [["claude", "mcp", "add", "server"]],
        }
    }
    run = MagicMock(side_effect=AssertionError("setup command ran during dry run"))
    monkeypatch.setattr(cmd_pull.subprocess, "run", run)

    result = _invoke(pull_app, target, "--dry-run")

    assert result.exit_code == 0, result.output
    assert list(target.iterdir()) == []
    assert result.output.count("would write") == 8
    assert "would clone  <skill:git-skill>" in result.output
    assert "Would run these setup commands" in result.output
    assert "$ claude mcp add server" in result.output
    boundaries.git_install.assert_not_called()
    boundaries.direct_install.assert_not_called()
    boundaries.upsert.assert_not_called()
    boundaries.snapshot.assert_not_called()
    boundaries.adapter.persist_active_agent.assert_not_called()
    boundaries.emit.assert_not_called()
    run.assert_not_called()


def test_pull_user_scope_expands_home_for_string_hook_and_agent_files(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    target = tmp_path / "project"
    target.mkdir()
    boundaries.adapter.allow_home_agent_profile.return_value = True
    boundaries.post.return_value = {
        "config_snippet": {
            "mcp_config": {
                "path": "~/.kiro/mcp.json",
                "content": {"mcpServers": {"server": {"command": "npx"}}},
            },
            "hooks_config": {
                "path": "~/.kiro/hooks.txt",
                "content": 'command = "observal-hook.sh --agent reviewer"\n',
            },
            "agent_profile": {
                "path": "~/.kiro/agents/reviewer.md",
                "content": 'stop = "observal-stop-hook.sh"\n',
            },
        }
    }
    monkeypatch.setattr(shutil, "which", lambda name: f"/opt/observal/{name}")

    result = _invoke(pull_app, target, "--scope", "user", harness="kiro")

    assert result.exit_code == 0, result.output
    assert "Files will be written to your home directory" in result.output
    assert json.loads((isolated_home / ".kiro" / "mcp.json").read_text()) == {
        "mcpServers": {"server": {"command": "npx"}}
    }
    assert (isolated_home / ".kiro" / "hooks.txt").read_text() == ('command = "/opt/observal/observal-hook.sh"\n')
    assert (isolated_home / ".kiro" / "agents" / "reviewer.md").read_text() == (
        'stop = "/opt/observal/observal-stop-hook.sh"\n'
    )
    assert list(target.iterdir()) == []
    boundaries.local_name.assert_called_once_with(
        "kiro",
        "agent",
        "acme",
        "reviewer",
        scope="user",
        directory=str(target.resolve()),
    )
    boundaries.upsert.assert_called_once()


def test_pull_partial_skill_failure_stops_metadata_updates_without_rolling_back_files(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
) -> None:
    target = tmp_path / "project"
    boundaries.git_install.side_effect = None
    boundaries.git_install.return_value = None
    boundaries.direct_install.side_effect = None
    boundaries.direct_install.return_value = None
    boundaries.post.return_value = {
        "config_snippet": {
            "agent_profile": {"path": "agent.md", "content": "written before skills\n"},
            "skill_components": [
                {"name": "git-failure", "git_url": "https://example.test/fail"},
                {"name": "direct-failure", "skill_md_content": None},
            ],
        }
    }

    result = _invoke(pull_app, target)

    assert result.exit_code == 9
    assert "Failed to install 2 agent skill(s)" in result.output
    assert (target / "agent.md").read_text() == "written before skills\n"
    boundaries.upsert.assert_not_called()
    boundaries.snapshot.assert_not_called()
    boundaries.adapter.persist_active_agent.assert_not_called()
    boundaries.emit.assert_not_called()


def test_pull_lockfile_failure_is_not_reported_as_success(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
) -> None:
    target = tmp_path / "project"
    boundaries.get.return_value = {"mcp_links": [], "component_links": []}
    boundaries.upsert.side_effect = OSError("lock unavailable")
    boundaries.snapshot.side_effect = RuntimeError("snapshot unavailable")
    boundaries.post.return_value = {"config_snippet": {"agent_profile": {"path": "agent.md", "content": "agent\n"}}}

    result = _invoke(pull_app, target, reference="name-only")

    assert result.exit_code == 9
    assert "installation tracking failed" in result.output
    assert (target / "agent.md").read_text() == "agent\n"
    boundaries.local_name.assert_called_once_with(
        "claude-code",
        "agent",
        "",
        "agent",
        scope="project",
        directory=str(target.resolve()),
    )
    boundaries.snapshot.assert_not_called()
    boundaries.adapter.persist_active_agent.assert_not_called()
    boundaries.emit.assert_not_called()


@pytest.mark.parametrize(
    ("snippet", "message", "metadata_written"),
    [
        ({}, "empty agent configuration", False),
        ({"scope": "project", "mcp_config": {"content": {}}}, "no writable files", False),
    ],
)
def test_pull_rejects_empty_or_unsupported_snippets(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
    snippet: dict,
    message: str,
    metadata_written: bool,
) -> None:
    boundaries.post.return_value = {"config_snippet": snippet}

    result = _invoke(pull_app, tmp_path / "project")

    assert result.exit_code == 9
    assert message.lower() in result.output.lower()
    assert boundaries.upsert.called is metadata_written
    assert boundaries.emit.called is metadata_written


def test_pull_required_and_unknown_harness_validation_stops_before_http(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
) -> None:
    missing = RUNNER.invoke(pull_app, ["agent", "pull", "agent-id"])
    assert missing.exit_code == 2
    assert "Missing option" in missing.output
    boundaries.resolve.assert_not_called()

    boundaries.get_adapter.side_effect = KeyError("unknown harness")
    unknown = _invoke(pull_app, tmp_path / "project", harness="unknown")
    assert unknown.exit_code == 7
    assert "Unknown harness" in unknown.output
    boundaries.get.assert_not_called()
    boundaries.post.assert_not_called()


def test_pull_server_scope_validation_failure_leaves_filesystem_clean(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
) -> None:
    target = tmp_path / "project"
    target.mkdir()
    seen = {}

    def reject_scope(_path: str, body: dict):
        seen.update(body)
        cmd_pull.rprint("[red]Invalid scope: workspace[/red]")
        raise typer.Exit(1)

    boundaries.post.side_effect = reject_scope

    result = _invoke(pull_app, target, "--scope", "workspace")

    assert result.exit_code == 7
    assert "Unknown install scope" in result.output
    assert seen == {}
    assert list(target.iterdir()) == []
    boundaries.upsert.assert_not_called()


def test_pull_path_traversal_stops_before_lockfile_update(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
) -> None:
    target = tmp_path / "project"
    boundaries.post.return_value = {
        "config_snippet": {"hook_files": [{"path": "../../escape.sh", "content": "unsafe"}]}
    }

    result = _invoke(pull_app, target)

    assert result.exit_code == 7
    assert "escapes the target directory" in result.output
    assert not (tmp_path.parent / "escape.sh").exists()
    boundaries.upsert.assert_not_called()
    boundaries.emit.assert_not_called()


def test_parse_assignments_rejects_missing_names_and_values():
    assert cmd_pull._parse_assignments(["TOKEN='secret'"], "environment variable") == {"TOKEN": "secret"}
    for invalid in ("TOKEN", "=secret", "TOKEN="):
        with pytest.raises(typer.Exit) as error:
            cmd_pull._parse_assignments([invalid], "environment variable")
        assert error.value.exit_code == 7


def test_toml_merge_is_idempotent_for_existing_server(tmp_path: Path):
    path = tmp_path / "config.toml"
    first = {"mcp_servers": {"github": {"command": "old"}}}
    second = {"mcp_servers": {"github": {"command": "new"}}}

    cmd_pull._write_file(path, first)
    cmd_pull._write_file(path, second, merge_mcp=True)
    cmd_pull._write_file(path, second, merge_mcp=True)

    assert tomllib.loads(path.read_text()) == second
    assert path.read_text().count("[mcp_servers.github]") == 1


def test_pull_json_returns_stable_file_and_setup_result_without_secrets(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
):
    target = tmp_path / "project"
    boundaries.post.return_value = {
        "config_snippet": {
            "agent_profile": {"path": "agent.md", "content": "agent\n"},
            "mcp_setup_commands": [[sys.executable, "-c", "pass"]],
        },
        "warnings": ["server warning"],
    }

    result = _invoke(
        pull_app,
        target,
        "--env",
        "TOKEN=secret-value",
        "--header",
        "Authorization=Bearer secret-value",
        "--output",
        "json",
    )

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    payload = json.loads(result.output)
    assert payload["agent"]["qualified_name"] == "acme/reviewer"
    assert payload["harness"] == "claude-code"
    assert payload["dry_run"] is False
    assert payload["files"] == [{"path": str(target.resolve() / "agent.md"), "status": "created"}]
    assert payload["warnings"] == ["server warning"]
    assert payload["setup_commands"][0]["status"] == "completed"
    assert "secret-value" not in result.output
    boundaries.upsert.assert_called_once()


def test_pull_json_dry_run_has_no_write_or_metadata_side_effects(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
):
    target = tmp_path / "project"
    boundaries.post.return_value = {
        "config_snippet": {
            "agent_profile": {"path": "agent.md", "content": "agent\n"},
            "mcp_setup_commands": [["claude", "mcp", "add", "server"]],
        }
    }

    result = _invoke(pull_app, target, "--dry-run", "--output", "json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["files"][0]["status"] == "would write"
    assert payload["setup_commands"][0]["status"] == "would_run"
    assert not target.exists()
    boundaries.upsert.assert_not_called()
    boundaries.emit.assert_not_called()


def test_pull_setup_failure_does_not_record_installation(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / "project"
    boundaries.post.return_value = {
        "config_snippet": {
            "agent_profile": {"path": "agent.md", "content": "agent\n"},
            "mcp_setup_commands": [["broken", "mcp", "add"]],
        }
    }
    monkeypatch.setattr(
        cmd_pull.subprocess,
        "run",
        MagicMock(return_value=subprocess.CompletedProcess(["broken"], 2, "", "failed")),
    )

    result = _invoke(pull_app, target)

    assert result.exit_code == 9
    assert (target / "agent.md").is_file()
    boundaries.upsert.assert_not_called()
    boundaries.emit.assert_not_called()


def test_pull_snapshot_failure_is_visible_warning(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
):
    target = tmp_path / "project"
    boundaries.snapshot.side_effect = RuntimeError("snapshot failed")
    boundaries.post.return_value = {"config_snippet": {"agent_profile": {"path": "agent.md", "content": "agent\n"}}}

    result = _invoke(pull_app, target, "--output", "json")

    assert result.exit_code == 0, result.output
    assert any(
        "Local layer snapshot could not be refreshed" in warning for warning in json.loads(result.output)["warnings"]
    )
    boundaries.upsert.assert_called_once()


def test_pull_rejects_malformed_existing_config_without_overwrite(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
):
    target = tmp_path / "project"
    path = target / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text("not-json")
    boundaries.post.return_value = {
        "config_snippet": {"mcp_config": {"path": "mcp.json", "content": {"mcpServers": {"new": {}}}}}
    }

    result = _invoke(pull_app, target)

    assert result.exit_code == 6
    assert path.read_text() == "not-json"
    boundaries.upsert.assert_not_called()


def test_pull_rejects_irrelevant_model_refresh_before_http(
    pull_app: typer.Typer,
    boundaries: SimpleNamespace,
    tmp_path: Path,
):
    result = _invoke(pull_app, tmp_path / "project", "--refresh-models")

    assert result.exit_code == 7
    assert "requires the interactive model picker" in result.output
    boundaries.resolve.assert_not_called()
    boundaries.get.assert_not_called()
