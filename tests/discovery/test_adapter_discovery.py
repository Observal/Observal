# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from observal_cli.discovery.models import DiagnosticCode, DiscoveryScope
from observal_cli.discovery.normalize import build_candidates, fingerprint_launch
from observal_cli.discovery.readiness import build_discovery_draft_payload
from observal_cli.discovery.serialize import adapter_discovery_result_to_dict
from observal_cli.harness.claude_code import ClaudeCodeAdapter
from observal_cli.harness.cursor import CursorAdapter
from observal_cli.harness.kiro import KiroAdapter
from observal_cli.harness.pi import PiAdapter
from observal_cli.harness.protocol import DiscoveredAgent, DiscoveredHook, DiscoveredMcp, DiscoveredSkill

if TYPE_CHECKING:
    from pathlib import Path


def _json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def _text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    return path


def _components(result, component_type):
    return [item.component for item in result.evidence if isinstance(item.component, component_type)]


def test_claude_discovers_independent_user_and_project_sources(tmp_path: Path) -> None:
    home = tmp_path / "home"
    claude = home / ".claude"
    plugin = tmp_path / "plugin"
    _json(
        claude / "settings.json",
        {
            "mcpServers": {"settings-mcp": {"command": "npx", "args": ["settings-mcp"]}},
            "hooks": {"Stop": [{"hooks": [{"command": "echo $TOKEN", "token": "secret-value"}]}]},
            "enabledPlugins": {"suite@market": True},
        },
    )
    _json(
        claude / "plugins" / "installed_plugins.json",
        {"plugins": {"suite@market": [{"installPath": str(plugin)}]}},
    )
    _json(plugin / ".mcp.json", {"mcpServers": {"plugin-mcp": {"url": "https://example.test/mcp?token=x"}}})
    _text(plugin / "skills" / "plugin-skill" / "SKILL.md", "---\ndescription: Plugin skill\n---\n")
    _text(claude / "skills" / "local" / "SKILL.md", "---\ndescription: Local skill\n---\n")
    _text(claude / "agents" / "reviewer.md", "---\nmodel: sonnet\n---\nReview safely")

    user = ClaudeCodeAdapter().discover_home(home)

    assert {item.name for item in _components(user, DiscoveredMcp)} == {"settings-mcp", "plugin-mcp"}
    assert {item.name for item in _components(user, DiscoveredSkill)} == {"local", "suite/plugin-skill"}
    assert [item.name for item in _components(user, DiscoveredAgent)] == ["reviewer"]
    hook = _components(user, DiscoveredHook)[0]
    assert hook.handler_config["token"] == "<secret>"
    plugin_mcp = next(item for item in _components(user, DiscoveredMcp) if item.name == "plugin-mcp")
    assert plugin_mcp.url == "https://example.test/mcp"
    assert all(item.scope is DiscoveryScope.USER and item.source_path is not None for item in user.evidence)

    project = tmp_path / "project"
    _json(project / ".mcp.json", {"mcpServers": {"project-mcp": {"command": "uvx", "args": ["server"]}}})
    _json(project / ".claude" / "settings.json", {"hooks": {"Stop": [{"command": "echo done"}]}})
    _text(project / ".claude" / "skills" / "project-skill" / "SKILL.md", "Project skill")
    _text(project / ".claude" / "agents" / "builder.md", "Build things")

    discovered = ClaudeCodeAdapter().discover_project(project)
    assert [item.name for item in _components(discovered, DiscoveredMcp)] == ["project-mcp"]
    assert [item.name for item in _components(discovered, DiscoveredSkill)] == ["project-skill"]
    assert [item.name for item in _components(discovered, DiscoveredAgent)] == ["builder"]
    assert [item.event for item in _components(discovered, DiscoveredHook)] == ["Stop"]


def test_mcp_launch_metadata_survives_adapter_normalization_without_secret_values(tmp_path: Path) -> None:
    secret_one = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
    secret_two = "sk-proj-zyxwvutsrqponmlkjihgfedcba654321"
    _json(
        tmp_path / ".cursor" / "mcp.json",
        {
            "mcpServers": {
                "env-one": {
                    "command": "npx",
                    "args": ["example-mcp"],
                    "env": {"ALPHA_TOKEN": secret_one},
                    "headers": {"Authorization": f"Bearer {secret_one}"},
                    "transport": "stdio",
                },
                "env-two": {
                    "command": "npx",
                    "args": ["example-mcp"],
                    "environment": {"BETA_TOKEN": secret_one},
                    "httpHeaders": {"X-API-Key": secret_one},
                    "type": "sse",
                },
                "same-names-new-values": {
                    "command": "npx",
                    "args": ["example-mcp"],
                    "env": {"ALPHA_TOKEN": secret_two},
                    "headers": {"Authorization": f"Bearer {secret_two}"},
                    "transport": "stdio",
                },
            }
        },
    )

    result = CursorAdapter().discover_home(tmp_path)
    evidence = {item.component.name: item for item in result.evidence}
    first = evidence["env-one"]
    second = evidence["env-two"]
    same_names = evidence["same-names-new-values"]
    assert first.launch is not None
    assert second.launch is not None
    assert same_names.launch is not None
    assert first.launch.environment_names == ("ALPHA_TOKEN",)
    assert first.launch.header_names == ("Authorization",)
    assert first.launch.transport == "stdio"
    assert second.launch.environment_names == ("BETA_TOKEN",)
    assert second.launch.header_names == ("X-API-Key",)
    assert second.launch.transport == "sse"
    assert fingerprint_launch(first.launch) != fingerprint_launch(second.launch)
    assert fingerprint_launch(first.launch) == fingerprint_launch(same_names.launch)

    serialized = json.dumps(adapter_discovery_result_to_dict(result), sort_keys=True)
    assert secret_one not in serialized
    assert secret_two not in serialized
    assert secret_one not in repr(result.diagnostics)
    assert secret_two not in repr(result.diagnostics)

    candidate = next(item for item in build_candidates(result.evidence) if item.local_name == "env-one")
    payload = build_discovery_draft_payload(candidate, owner="alice")
    assert payload["environment_variables"] == [{"name": "ALPHA_TOKEN", "description": "", "required": True}]
    assert payload["headers"] == [{"name": "Authorization", "description": "", "required": True}]
    assert payload["transport"] == "stdio"
    assert secret_one not in repr(payload)
    assert secret_two not in repr(payload)


@pytest.mark.parametrize(
    ("metadata", "diagnostic_code"),
    [
        ({"env": "API_KEY=secret-value"}, DiagnosticCode.METADATA_MALFORMED),
        ({"headers": "Authorization: secret-value"}, DiagnosticCode.METADATA_MALFORMED),
        ({"transport": "future-custom-transport"}, DiagnosticCode.UNSUPPORTED_LAUNCH),
    ],
)
def test_malformed_mcp_metadata_is_incomplete_and_diagnosed(
    tmp_path: Path, metadata: dict, diagnostic_code: DiagnosticCode
) -> None:
    _json(
        tmp_path / ".cursor" / "mcp.json",
        {"mcpServers": {"unsafe": {"command": "npx", "args": ["example-mcp"], **metadata}}},
    )

    result = CursorAdapter().discover_home(tmp_path)
    candidate = build_candidates(result.evidence)[0]
    serialized = json.dumps(adapter_discovery_result_to_dict(result), sort_keys=True)

    assert result.evidence[0].launch is None
    assert candidate.launch_fingerprint is None
    assert candidate.registration_status.value == "incomplete"
    assert candidate.support_status.value == "unsupported"
    assert [item.code for item in result.diagnostics] == [diagnostic_code]
    assert "secret-value" not in serialized
    assert "future-custom-transport" not in serialized
    assert "secret-value" not in repr(result.diagnostics)
    assert "future-custom-transport" not in repr(result.diagnostics)


def test_claude_plugin_traversal_skips_oversized_and_deep_skills(tmp_path: Path) -> None:
    claude = tmp_path / ".claude"
    plugin = tmp_path / "plugin"
    _json(claude / "settings.json", {"enabledPlugins": {"suite@market": True}})
    _json(
        claude / "plugins" / "installed_plugins.json",
        {"plugins": {"suite@market": [{"installPath": str(plugin)}]}},
    )
    _text(plugin / "skills" / "large" / "SKILL.md", "x" * (1024 * 1024 + 1))
    deep = plugin
    for index in range(9):
        deep = deep / str(index)
    _text(deep / "SKILL.md", "Too deep")

    result = ClaudeCodeAdapter().discover_home(tmp_path)

    assert _components(result, DiscoveredSkill) == []
    codes = {item.code for item in result.diagnostics}
    assert DiagnosticCode.METADATA_TOO_LARGE in codes
    assert DiagnosticCode.RECURSION_LIMIT_REACHED in codes


def test_claude_skills_and_agents_do_not_require_settings(tmp_path: Path) -> None:
    _text(tmp_path / ".claude" / "skills" / "helper" / "SKILL.md", "Helps")
    _text(tmp_path / ".claude" / "agents" / "reviewer.md", "Reviews")

    result = ClaudeCodeAdapter().discover_home(tmp_path)

    assert [item.name for item in _components(result, DiscoveredSkill)] == ["helper"]
    assert [item.name for item in _components(result, DiscoveredAgent)] == ["reviewer"]


def test_cursor_discovers_all_documented_sources_and_reports_malformed_files(tmp_path: Path) -> None:
    root = tmp_path / ".cursor"
    _json(root / "mcp.json", {"mcpServers": {"server": {"command": "node", "args": ["server.js"]}}})
    _text(root / "agents" / "reviewer.md", "---\ndescription: Reviews\n---\nPrompt")
    _text(root / "skills" / "helper" / "SKILL.md", "---\ndescription: Helps\n---\n")
    _text(root / "hooks.json", "{ malformed")

    result = CursorAdapter().discover_home(tmp_path)

    assert [item.name for item in _components(result, DiscoveredMcp)] == ["server"]
    assert [item.name for item in _components(result, DiscoveredAgent)] == ["reviewer"]
    assert [item.name for item in _components(result, DiscoveredSkill)] == ["helper"]
    assert [item.code for item in result.diagnostics] == [DiagnosticCode.METADATA_MALFORMED]


def test_cursor_project_uses_project_scope_and_paths(tmp_path: Path) -> None:
    _json(tmp_path / ".cursor" / "hooks.json", {"hooks": {"Stop": [{"command": "echo done"}]}})
    _text(tmp_path / ".cursor" / "agents" / "builder.md", "Build")

    result = CursorAdapter().discover_project(tmp_path)

    assert all(item.scope is DiscoveryScope.PROJECT for item in result.evidence)
    assert [item.name for item in _components(result, DiscoveredAgent)] == ["builder"]
    assert [item.event for item in _components(result, DiscoveredHook)] == ["Stop"]


def test_pi_discovers_agent_and_excludes_managed_telemetry_extension(tmp_path: Path) -> None:
    root = tmp_path / ".pi" / "agent"
    _json(root / "mcp.json", {"mcpServers": {"server": {"command": "npx", "args": ["server"]}}})
    _text(root / "skills" / "helper" / "SKILL.md", "Helps")
    _text(root / "AGENTS.md", "Pi agent guidance")
    _json(root / "settings.json", {"extensions": ["extensions/observal.ts", "extensions/audit.ts"]})

    result = PiAdapter().discover_home(tmp_path)

    assert [item.name for item in _components(result, DiscoveredMcp)] == ["server"]
    assert [item.name for item in _components(result, DiscoveredSkill)] == ["helper"]
    assert [item.name for item in _components(result, DiscoveredAgent)] == ["pi-agent"]
    hooks = _components(result, DiscoveredHook)
    assert [(item.name, item.handler_type) for item in hooks] == [("audit", "extension")]


def test_pi_project_agent_uses_root_agents_md_not_guidance_files(tmp_path: Path) -> None:
    _text(tmp_path / "AGENTS.md", "Project agent")
    _text(tmp_path / ".pi" / "SYSTEM.md", "Not standalone")
    _text(tmp_path / ".pi" / "APPEND_SYSTEM.md", "Not standalone")

    result = PiAdapter().discover_project(tmp_path)

    assert [item.name for item in _components(result, DiscoveredAgent)] == ["pi-agent"]
    assert len(result.evidence) == 1


def test_kiro_home_uses_the_same_root_scanner(tmp_path: Path) -> None:
    _text(tmp_path / ".kiro" / "skills" / "home-helper" / "SKILL.md", "Helps")

    result = KiroAdapter().discover_home(tmp_path)

    assert [item.name for item in _components(result, DiscoveredSkill)] == ["home-helper"]
    assert result.evidence[0].scope is DiscoveryScope.USER


def test_kiro_project_discovers_root_sources_and_preserves_distinct_same_name_mcps(tmp_path: Path) -> None:
    root = tmp_path / ".kiro"
    _json(root / "settings" / "mcp.json", {"mcpServers": {"shared": {"command": "npx", "args": ["one"]}}})
    _json(
        root / "agents" / "coder.json",
        {
            "name": "coder",
            "prompt": "Code",
            "mcpServers": {"shared": {"command": "npx", "args": ["two"]}},
            "hooks": {"preToolUse": [{"command": "echo pre", "password": "hidden"}]},
        },
    )
    _text(root / "skills" / "helper" / "SKILL.md", "Helps")
    _json(root / "hooks" / "audit.json", {"name": "audit", "event": "stop", "command": "echo done"})

    result = KiroAdapter().discover_project(tmp_path)

    mcps = _components(result, DiscoveredMcp)
    assert [(item.name, item.args) for item in mcps] == [("shared", ["two"]), ("shared", ["one"])]
    assert [item.name for item in _components(result, DiscoveredAgent)] == ["coder"]
    assert [item.name for item in _components(result, DiscoveredSkill)] == ["helper"]
    hooks = _components(result, DiscoveredHook)
    assert {item.name for item in hooks} == {"audit", "kiro:coder/preToolUse"}
    embedded = next(item for item in hooks if item.name.startswith("kiro:coder"))
    assert embedded.handler_config["password"] == "<secret>"
