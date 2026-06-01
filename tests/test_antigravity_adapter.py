# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the Antigravity CLI IDE adapter."""

from __future__ import annotations

import json

import pytest

from observal_cli.ide import HookSpec, ScanResult, ensure_loaded, get_adapter
from schemas.ide_registry import IDE_REGISTRY


@pytest.fixture(autouse=True)
def _load_adapters():
    ensure_loaded()


# ── Registry ──────────────────────────────────────────────────────────────────


def test_antigravity_in_registry():
    assert "antigravity" in IDE_REGISTRY


def test_antigravity_registry_required_keys():
    spec = IDE_REGISTRY["antigravity"]
    required = {
        "display_name",
        "features",
        "scopes",
        "default_scope",
        "rules_file",
        "mcp_config_path",
        "mcp_servers_key",
        "hook_config_path",
        "hook_events_map",
    }
    assert required <= set(spec.keys())


def test_antigravity_registry_mcp_servers_key():
    assert IDE_REGISTRY["antigravity"]["mcp_servers_key"] == "mcpServers"


def test_antigravity_registry_hook_events_map():
    events = IDE_REGISTRY["antigravity"]["hook_events_map"]
    assert "PreToolUse" in events
    assert "Stop" in events
    assert "SessionStart" in events


# ── Adapter registration ───────────────────────────────────────────────────────


def test_antigravity_adapter_registered():
    adapter = get_adapter("antigravity")
    assert adapter.ide_name == "antigravity"


def test_antigravity_adapter_has_required_methods():
    adapter = get_adapter("antigravity")
    for method in ("scan_home", "scan_project", "get_hook_spec", "generate_hook_config", "detect_hooks", "shim_status"):
        assert callable(getattr(adapter, method))


# ── scan_home ─────────────────────────────────────────────────────────────────


def test_scan_home_empty_dir(tmp_path):
    result = get_adapter("antigravity").scan_home(home=tmp_path)
    assert isinstance(result, ScanResult)
    assert result.mcps == []


def test_scan_home_reads_global_mcps(tmp_path):
    ag_dir = tmp_path / ".gemini" / "antigravity-cli"
    ag_dir.mkdir(parents=True)
    mcp_data = {
        "mcpServers": {
            "my-server": {"command": "node", "args": ["server.js"]},
            "remote-server": {"serverUrl": "https://api.example.com/mcp/"},
        }
    }
    (ag_dir / "mcp_config.json").write_text(json.dumps(mcp_data))

    result = get_adapter("antigravity").scan_home(home=tmp_path)
    names = {m.name for m in result.mcps}
    assert "my-server" in names
    assert "remote-server" in names


def test_scan_home_remote_mcp_uses_server_url(tmp_path):
    ag_dir = tmp_path / ".gemini" / "antigravity-cli"
    ag_dir.mkdir(parents=True)
    mcp_data = {"mcpServers": {"remote": {"serverUrl": "https://api.example.com/mcp/"}}}
    (ag_dir / "mcp_config.json").write_text(json.dumps(mcp_data))

    result = get_adapter("antigravity").scan_home(home=tmp_path)
    remote = next(m for m in result.mcps if m.name == "remote")
    assert remote.url == "https://api.example.com/mcp/"


def test_scan_home_reads_hooks_from_settings(tmp_path):
    ag_dir = tmp_path / ".gemini" / "antigravity-cli"
    ag_dir.mkdir(parents=True)
    settings = {"hooks": {"pre_turn": [{"command": "observal-push"}]}}
    (ag_dir / "settings.json").write_text(json.dumps(settings))

    result = get_adapter("antigravity").scan_home(home=tmp_path)
    assert len(result.hooks) == 1
    assert result.hooks[0].event == "pre_turn"


def test_scan_home_reads_skills(tmp_path):
    skills_dir = tmp_path / ".gemini" / "antigravity-cli" / "skills" / "my-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("---\ndescription: A test skill\n---\nContent here.")

    result = get_adapter("antigravity").scan_home(home=tmp_path)
    assert any(s.name == "my-skill" for s in result.skills)


# ── scan_project ──────────────────────────────────────────────────────────────


def test_scan_project_empty_dir(tmp_path):
    result = get_adapter("antigravity").scan_project(tmp_path)
    assert isinstance(result, ScanResult)
    assert result.mcps == []


def test_scan_project_reads_mcps(tmp_path):
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    mcp_data = {"mcpServers": {"proj-mcp": {"command": "python", "args": ["-m", "mcp"]}}}
    (agents_dir / "mcp_config.json").write_text(json.dumps(mcp_data))

    result = get_adapter("antigravity").scan_project(tmp_path)
    assert any(m.name == "proj-mcp" for m in result.mcps)


# ── Hook spec & detection ─────────────────────────────────────────────────────


def test_get_hook_spec_returns_hook_spec():
    spec = get_adapter("antigravity").get_hook_spec()
    assert isinstance(spec, HookSpec)
    assert "pre_turn" in spec.events or "PreTurn" in spec.events or len(spec.events) > 0
    assert spec.format == "command"


def test_generate_hook_config_returns_dict():
    config = get_adapter("antigravity").generate_hook_config(
        observal_url="http://localhost:8000",
        api_key="test-key",
    )
    assert isinstance(config, dict)
    assert "observal-telemetry" in config
    hook_def = config["observal-telemetry"]
    assert "PreInvocation" in hook_def or "Stop" in hook_def


def test_detect_hooks_missing_when_no_settings(tmp_path):
    # Create an empty hooks.json so the adapter uses tmp_path instead of falling back to real config
    (tmp_path / "hooks.json").write_text("{}")
    result = get_adapter("antigravity").detect_hooks(tmp_path)
    assert result == "missing"


def test_detect_hooks_installed(tmp_path):
    hooks = {
        "observal-telemetry": {
            "PreInvocation": [
                {
                    "hooks": [
                        {"type": "command", "command": "wsl.exe python3 -m observal_cli.hooks.antigravity_session_push"}
                    ]
                }
            ]
        }
    }
    (tmp_path / "hooks.json").write_text(json.dumps(hooks))
    result = get_adapter("antigravity").detect_hooks(tmp_path)
    assert result == "installed"


def test_detect_hooks_missing_when_no_observal_marker(tmp_path):
    hooks = {"some-other-hook": {"PreInvocation": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
    (tmp_path / "hooks.json").write_text(json.dumps(hooks))
    result = get_adapter("antigravity").detect_hooks(tmp_path)
    assert result == "missing"


# ── shim_status ───────────────────────────────────────────────────────────────


def test_shim_status_no_mcps():
    assert get_adapter("antigravity").shim_status([]) == "none"
