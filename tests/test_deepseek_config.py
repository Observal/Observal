# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Native DeepSeek Cordis patch and on-demand skill generation."""

from __future__ import annotations

import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_current_user, get_db
from api.routes.preview import router
from services.config_generator import generate_config
from services.harness import McpConfigContext, generate_agent_config, generate_all_harness_configs, get_adapter
from services.harness.deepseek import _server_name


def agent(*, components=None, external_mcps=None, description="", prompt="Keep responses short."):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="example",
        description=description,
        prompt=prompt,
        model_name="model-owned-by-dsh",
        components=components or [],
        external_mcps=external_mcps or [],
        required_capabilities=[],
    )


def listing(**kwargs):
    values = {
        "id": uuid.uuid4(),
        "name": "registry-server",
        "slug": "registry-server",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "server"],
        "url": None,
        "framework": "typescript",
        "docker_image": None,
        "environment_variables": [{"name": "TOKEN"}],
        "auto_approve": [],
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


def entries(config):
    patches = config["mcp_config"]["content"]
    assert isinstance(patches, list)
    assert all(set(patch) == {"insert"} and len(patch["insert"]) == 1 for patch in patches)
    return [patch["insert"][0] for patch in patches]


def mcp_context(**overrides):
    values = dict(
        name="registry-server",
        command="npx",
        args=["-y", "pkg"],
        server_env={"TOKEN": "secret"},
        headers={},
        transport="stdio",
        url=None,
        auto_approve=[],
    )
    values.update(overrides)
    return McpConfigContext(**values)


def test_registry_stdio_and_direct_install_are_native():
    item = listing()
    comp = SimpleNamespace(component_id=item.id, component_type="mcp")
    instance = agent(components=[comp])
    config = generate_agent_config(
        instance, "deepseek", mcp_listings={item.id: item}, env_values={str(item.id): {"TOKEN": "secret"}}
    )
    collector, server = entries(config)
    assert collector == {
        "id": "observal-session-collector",
        "name": "~/.dsh/observal/collector.mjs",
        "config": {"pythonPath": "<runtime-python>", "dshHome": "<runtime-dsh-home>"},
    }
    assert "hooks_config" not in config
    assert server == {
        "id": "observal-mcp-registry-server",
        "name": "@deepseek-ai/dsh-mcp-client",
        "config": {
            "serverName": "registry-server",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "server"],
            "env": {"TOKEN": "secret", "OBSERVAL_AGENT_ID": str(instance.id)},
        },
    }
    assert "mcpServers" not in config
    direct = generate_config(item, "deepseek", env_values={"TOKEN": "secret"})
    assert direct["path"] == "~/.dsh/cordis.patch.yml"
    assert direct["content"][0]["insert"][0]["config"]["serverName"] == "registry-server"
    assert "merge" in direct["_note"].lower()


def test_http_preserves_headers_and_explicit_sse_fails():
    item = listing(transport="streamable-http", url="https://mcp.example/api")
    comp = SimpleNamespace(component_id=item.id, component_type="mcp")
    config = generate_agent_config(
        agent(components=[comp]),
        "deepseek",
        mcp_listings={item.id: item},
        header_values={str(item.id): {"Authorization": "Bearer secret"}},
    )
    server = entries(config)[1]
    assert server["config"] == {
        "serverName": "registry-server",
        "transport": "streamable-http",
        "url": "https://mcp.example/api",
        "headers": {"Authorization": "Bearer secret"},
    }
    with pytest.raises(ValueError, match="legacy SSE"):
        generate_config(listing(transport="sse", url="https://legacy.example/sse"), "deepseek")
    with pytest.raises(ValueError, match="legacy SSE"):
        generate_agent_config(
            agent(components=[comp]),
            "deepseek",
            mcp_listings={item.id: listing(id=item.id, transport="sse", url=item.url)},
        )


def test_external_and_sandbox_stdio_entries_use_identical_native_rows():
    ext = {"name": "external", "command": "node", "args": ["server.js"], "env": {"KEY": "value"}}
    # Sandbox metadata is supplied to the shared sandbox-MCP builder.
    sandbox_id = uuid.uuid4()
    sandbox_meta = SimpleNamespace(
        id=sandbox_id,
        name="isolated",
        slug="isolated",
        image="image:latest",
        runtime_type="docker",
        entrypoint="bash",
        resource_limits={},
        runtime_config={},
        network_policy="none",
    )
    config = generate_agent_config(agent(external_mcps=[ext]), "deepseek", sandbox_listings={sandbox_id: sandbox_meta})
    servers = {row["config"]["serverName"]: row for row in entries(config)[1:]}
    assert servers["external"]["config"]["command"] == "node"
    assert servers["external"]["config"]["env"]["KEY"] == "value"
    assert servers["observal-sandbox"]["config"]["command"] == "python3"
    assert "observal_cli.sandbox_mcp" in servers["observal-sandbox"]["config"]["args"]
    assert all(row["id"].startswith("observal-mcp-") for row in servers.values())
    assert "OTEL_" not in str(config)


def test_external_http_transport_and_sse_rejection():
    remote = {
        "name": "external-http",
        "url": "https://mcp.example/mcp",
        "transport": "streamable-http",
        "headers": {"Authorization": "Bearer token"},
    }
    config = generate_agent_config(agent(external_mcps=[remote]), "deepseek")
    server = entries(config)[1]["config"]
    assert server == {
        "serverName": "external-http",
        "transport": "streamable-http",
        "url": "https://mcp.example/mcp",
        "headers": remote["headers"],
    }
    remote["transport"] = "sse"
    with pytest.raises(ValueError, match="legacy SSE"):
        generate_agent_config(agent(external_mcps=[remote]), "deepseek")


def test_name_normalization_is_native_length_safe_and_collision_resistant():
    assert _server_name("short-name_1") == "short-name_1"
    names = ["a" * 50 + "a", "a" * 50 + "b", "a/b", "a?b", "!!!"]
    converted = [_server_name(name) for name in names]
    assert len(set(converted)) == len(names)
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name) for name in converted)
    ctx = mcp_context(name="repo/" + "x" * 80)
    direct = get_adapter("deepseek").format_mcp_config(ctx)
    assert direct["content"][0]["insert"][0]["id"] == f"observal-mcp-{_server_name(ctx.name)}"


@pytest.mark.parametrize(
    "scope,path",
    [
        ("project", ".dsh/skills/observal-example/SKILL.md"),
        ("user", "~/.dsh/skills/observal-example/SKILL.md"),
    ],
)
def test_on_demand_skill_and_user_scoped_activation(scope, path):
    config = generate_agent_config(agent(description='Description: "quoted"'), "deepseek", options={"scope": scope})
    assert config["agent_profile"]["path"] == path
    content = config["agent_profile"]["content"]
    frontmatter = yaml.safe_load(content.split("---", 2)[1])
    assert frontmatter == {"name": "observal-example", "description": 'Description: "quoted"'}
    assert "Keep responses short." in content
    assert config["mcp_config"]["path"] == "~/.dsh/cordis.patch.yml"
    assert entries(config) == [
        {
            "id": "observal-session-collector",
            "name": "~/.dsh/observal/collector.mjs",
            "config": {"pythonPath": "<runtime-python>", "dshHome": "<runtime-dsh-home>"},
        }
    ]
    assert "hooks_config" not in config
    assert all("model" not in row["config"] for row in entries(config))
    assert "explicitly" in " ".join(config["_warnings"])
    if scope == "project":
        assert "user DSH_HOME" in " ".join(config["_warnings"])
    assert "agent.json" not in str(config)


def test_command_hook_components_are_nested_under_bridge_rules():
    item_id = uuid.uuid4()
    comp = SimpleNamespace(component_id=item_id, component_type="hook")
    hook = SimpleNamespace(
        event="PreToolUse",
        handler_type="command",
        handler_config={"command": "run-check"},
        name="check",
        slug="check",
        script_filename=None,
        script_content=None,
    )
    config = generate_agent_config(agent(components=[comp]), "deepseek", hook_listings={item_id: hook})
    assert [row["id"] for row in entries(config)] == ["observal-session-collector", "observal-hooks"]
    assert config["hooks_config"]["content"]["hooks"]["PreToolUse"] == [
        {"hooks": [{"type": "command", "command": "run-check"}]},
    ]
    adapter = get_adapter("deepseek")
    snippet = adapter.format_hook_install_snippet("PostToolUse", "command", "test-command", 12)
    assert snippet["hooks"]["PostToolUse"] == [
        {"hooks": [{"type": "command", "command": "test-command", "timeout": 12}]}
    ]
    assert "JSON alone does not activate" in snippet["_note"]
    assert "cordis.patch.yml" in adapter.hook_install_notes()[0]
    with pytest.raises(ValueError, match="command hooks only"):
        adapter.format_hook_install_snippet("PreToolUse", "http", "", None)
    hook.handler_type = "http"
    with pytest.raises(ValueError, match="command hooks only"):
        generate_agent_config(agent(components=[comp]), "deepseek", hook_listings={item_id: hook})


@pytest.mark.asyncio
async def test_hook_scripts_are_user_scoped_and_included_in_archives():
    item_id = uuid.uuid4()
    comp = SimpleNamespace(component_id=item_id, component_type="hook")
    hook = SimpleNamespace(
        event="PreToolUse",
        handler_type="command",
        handler_config={},
        name="check",
        slug="check",
        script_filename="check.sh",
        script_content="#!/bin/sh\necho checked\n",
    )
    instance = agent(components=[comp])
    config = generate_agent_config(instance, "deepseek", hook_listings={item_id: hook}, options={"scope": "project"})
    script_path = "~/.dsh/observal/scripts/check.sh"
    assert config["hook_files"] == [{"path": script_path, "content": hook.script_content, "executable": True}]
    assert config["hooks_config"]["content"]["hooks"]["PreToolUse"][-1] == {
        "hooks": [{"type": "command", "command": script_path}]
    }
    archive = await generate_all_harness_configs(
        SimpleNamespace(supported_harnesses=["deepseek"]), instance, hook_listings={item_id: hook}
    )
    assert archive["deepseek"]["files"][script_path] == hook.script_content


def test_skill_components_remain_available_to_shared_installer():
    item_id = uuid.uuid4()
    comp = SimpleNamespace(component_id=item_id, component_type="skill")
    skill = SimpleNamespace(
        name="helper",
        slug="helper",
        description="Helpful",
        slash_command=None,
        task_type="",
        git_url=None,
        git_ref=None,
        skill_path=None,
        skill_md_content="---\nname: helper\n---\nHelp",
        script_content=None,
        script_filename=None,
    )
    config = generate_agent_config(agent(components=[comp]), "deepseek", skill_listings={item_id: skill})
    assert config["skill_components"][0]["name"] == "helper"
    assert config["skill_components"][0]["skill_md_content"].endswith("Help")


@pytest.mark.asyncio
async def test_preview_and_archived_generated_files_are_yaml_sequences():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: MagicMock()
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/agents/preview-config",
            json={"name": "example", "prompt": "Hello", "target_harnesses": ["deepseek"]},
        )
    assert response.status_code == 200
    files = response.json()["configs"]["deepseek"]
    patches = yaml.safe_load(files["~/.dsh/cordis.patch.yml"])
    assert patches[0]["insert"][0]["id"] == "observal-session-collector"
    assert "'insert':" not in files["~/.dsh/cordis.patch.yml"]
    assert files["~/.dsh/skills/observal-example/SKILL.md"].startswith("---\n")
    archived = await generate_all_harness_configs(SimpleNamespace(supported_harnesses=["deepseek"]), agent())
    assert yaml.safe_load(archived["deepseek"]["files"]["~/.dsh/cordis.patch.yml"]) == patches
    assert "~/.dsh/observal/hooks.json" not in archived["deepseek"]["files"]
