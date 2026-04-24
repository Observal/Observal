"""Tests for agent_config_generator and agent_builder IDE generation.

Covers the server-side code that converts an Agent model into
IDE-specific config files (rules, frontmatter, MCP configs) and
the manifest-based builder that does the same from AgentManifest.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import yaml

from services.agent_builder import (
    AgentManifest,
    ManifestComponent,
    ManifestComponents,
    generate_ide_agent_files,
)
from services.agent_config_generator import (
    _build_rules_content,
    _inject_agent_id,
    _sanitize_name,
    generate_agent_config,
)

# ── Helpers ───────────────────────────────────────────────────────


def _make_component(component_type: str = "mcp", component_id: uuid.UUID | None = None) -> MagicMock:
    comp = MagicMock()
    comp.component_type = component_type
    comp.component_id = component_id or uuid.uuid4()
    return comp


def _make_agent(
    name: str = "test-agent",
    description: str = "A test agent",
    prompt: str = "You are helpful.",
    model_name: str = "claude-sonnet-4",
    components: list | None = None,
    external_mcps: list | None = None,
) -> MagicMock:
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.name = name
    agent.description = description
    agent.prompt = prompt
    agent.model_name = model_name
    agent.components = components or []
    agent.external_mcps = external_mcps or []
    return agent


def _make_manifest(
    name: str = "test-agent",
    description: str = "A test agent",
    prompt: str = "You are helpful.",
    model_name: str = "claude-sonnet-4",
    mcps: list[ManifestComponent] | None = None,
    skills: list[ManifestComponent] | None = None,
    hooks: list[ManifestComponent] | None = None,
    prompts: list[ManifestComponent] | None = None,
) -> AgentManifest:
    return AgentManifest(
        name=name,
        version="1.0.0",
        description=description,
        prompt=prompt,
        model_name=model_name,
        components=ManifestComponents(
            mcps=mcps or [],
            skills=skills or [],
            hooks=hooks or [],
            prompts=prompts or [],
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 1. _sanitize_name
# ═══════════════════════════════════════════════════════════════════


class TestSanitizeName:
    def test_passthrough_for_safe_name(self):
        assert _sanitize_name("my-agent_v2") == "my-agent_v2"

    def test_replaces_spaces_and_special_chars(self):
        assert _sanitize_name("my agent!@#v2") == "my-agent---v2"

    def test_empty_string(self):
        assert _sanitize_name("") == ""

    def test_all_special_chars(self):
        result = _sanitize_name("!!!???")
        assert all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in result)


# ═══════════════════════════════════════════════════════════════════
# 2. _inject_agent_id
# ═══════════════════════════════════════════════════════════════════


class TestInjectAgentId:
    def test_adds_env_var_to_all_entries(self):
        configs = {
            "server-a": {"command": "npx", "args": [], "env": {}},
            "server-b": {"command": "node", "args": ["s.js"], "env": {"FOO": "bar"}},
        }
        _inject_agent_id(configs, "agent-123")
        assert configs["server-a"]["env"]["OBSERVAL_AGENT_ID"] == "agent-123"
        assert configs["server-b"]["env"]["OBSERVAL_AGENT_ID"] == "agent-123"
        assert configs["server-b"]["env"]["FOO"] == "bar"

    def test_creates_env_if_missing(self):
        configs = {"srv": {"command": "x"}}
        _inject_agent_id(configs, "id-1")
        assert configs["srv"]["env"]["OBSERVAL_AGENT_ID"] == "id-1"

    def test_skips_non_dict_values(self):
        configs = {"meta": "not-a-dict", "srv": {"command": "x", "env": {}}}
        _inject_agent_id(configs, "id-1")
        assert configs["meta"] == "not-a-dict"


# ═══════════════════════════════════════════════════════════════════
# 3. _build_rules_content
# ═══════════════════════════════════════════════════════════════════


class TestBuildRulesContent:
    def test_uses_prompt_when_available(self):
        agent = _make_agent(prompt="Custom prompt", description="Desc")
        result = _build_rules_content(agent)
        assert "Custom prompt" in result
        assert "Desc" not in result

    def test_falls_back_to_description_when_no_prompt(self):
        agent = _make_agent(prompt="", description="Agent description")
        result = _build_rules_content(agent)
        assert "Agent description" in result

    def test_fallback_when_both_empty(self):
        agent = _make_agent(prompt="", description="")
        result = _build_rules_content(agent)
        assert agent.name in result

    def test_includes_component_summaries(self):
        mcp_id = uuid.uuid4()
        skill_id = uuid.uuid4()
        components = [
            _make_component("mcp", mcp_id),
            _make_component("skill", skill_id),
        ]
        names = {str(mcp_id): "my-mcp-server", str(skill_id): "my-skill"}
        agent = _make_agent(components=components)

        result = _build_rules_content(agent, component_names=names)
        assert "## MCP Servers" in result
        assert "**my-mcp-server**" in result
        assert "## Skills" in result
        assert "**my-skill**" in result

    def test_truncates_component_id_when_no_name_provided(self):
        comp_id = uuid.uuid4()
        agent = _make_agent(components=[_make_component("mcp", comp_id)])
        result = _build_rules_content(agent)
        assert str(comp_id)[:8] in result

    def test_groups_multiple_components_by_type(self):
        id1, id2 = uuid.uuid4(), uuid.uuid4()
        components = [_make_component("hook", id1), _make_component("hook", id2)]
        names = {str(id1): "hook-a", str(id2): "hook-b"}
        agent = _make_agent(components=components)
        result = _build_rules_content(agent, component_names=names)
        assert "## Hooks" in result
        assert "**hook-a**" in result
        assert "**hook-b**" in result

    def test_never_returns_empty(self):
        agent = _make_agent(prompt="", description="", components=[])
        result = _build_rules_content(agent)
        assert len(result.strip()) > 0


# ═══════════════════════════════════════════════════════════════════
# 4. generate_agent_config — Claude Code
# ═══════════════════════════════════════════════════════════════════


class TestGenerateClaudeCode:
    def test_path_is_under_agents_not_rules(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "claude-code")
        path = cfg["rules_file"]["path"]
        assert ".claude/agents/" in path
        assert ".claude/rules/" not in path

    def test_content_starts_with_yaml_frontmatter(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "claude-code")
        content = cfg["rules_file"]["content"]
        assert content.startswith("---\n")
        # Extract frontmatter
        parts = content.split("---", 2)
        assert len(parts) >= 3
        fm = yaml.safe_load(parts[1])
        assert fm["name"] == "test-agent"
        assert "A test agent" in fm["description"]

    def test_frontmatter_includes_mcp_servers(self):
        ext_mcps = [{"name": "my-ext", "command": "npx", "args": ["-y", "ext"]}]
        agent = _make_agent(external_mcps=ext_mcps)
        cfg = generate_agent_config(agent, "claude-code")
        content = cfg["rules_file"]["content"]
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1])
        assert "mcpServers" in fm
        assert "my-ext" in fm["mcpServers"]

    def test_frontmatter_omits_mcpservers_when_empty(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "claude-code")
        content = cfg["rules_file"]["content"]
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1])
        assert "mcpServers" not in fm or fm.get("mcpServers") is None

    def test_body_contains_rules_content(self):
        agent = _make_agent(prompt="Be very helpful.")
        cfg = generate_agent_config(agent, "claude-code")
        content = cfg["rules_file"]["content"]
        assert "Be very helpful." in content

    def test_setup_commands_generated_for_external_mcps(self):
        ext_mcps = [{"name": "srv", "command": "npx", "args": ["-y", "srv"]}]
        agent = _make_agent(external_mcps=ext_mcps)
        cfg = generate_agent_config(agent, "claude-code")
        assert "mcp_setup_commands" in cfg
        assert len(cfg["mcp_setup_commands"]) == 1
        cmd = cfg["mcp_setup_commands"][0]
        assert cmd[0:4] == ["claude", "mcp", "add", "srv"]

    def test_otlp_env_present(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "claude-code")
        assert "otlp_env" in cfg
        assert "CLAUDE_CODE_ENABLE_TELEMETRY" in cfg["otlp_env"]

    def test_claude_code_underscore_alias(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "claude_code")
        assert ".claude/agents/" in cfg["rules_file"]["path"]

    def test_multiline_description_collapsed(self):
        agent = _make_agent(description="Line one\nLine two\nLine three")
        cfg = generate_agent_config(agent, "claude-code")
        content = cfg["rules_file"]["content"]
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1])
        assert "\n" not in fm["description"]


# ═══════════════════════════════════════════════════════════════════
# 5. generate_agent_config — Cursor / VSCode
# ═══════════════════════════════════════════════════════════════════


class TestGenerateCursorVscode:
    def test_cursor_paths(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "cursor")
        assert cfg["rules_file"]["path"] == ".cursor/rules/test-agent.md"
        assert cfg["mcp_config"]["path"] == ".cursor/mcp.json"

    def test_vscode_paths(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "vscode")
        assert cfg["rules_file"]["path"] == ".vscode/rules/test-agent.md"
        assert cfg["mcp_config"]["path"] == ".vscode/mcp.json"

    def test_rules_content_not_empty(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "cursor")
        assert len(cfg["rules_file"]["content"]) > 0

    def test_mcp_config_has_mcpservers_key(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "cursor")
        assert "mcpServers" in cfg["mcp_config"]["content"]


# ═══════════════════════════════════════════════════════════════════
# 6. generate_agent_config — Kiro
# ═══════════════════════════════════════════════════════════════════


class TestGenerateKiro:
    def test_agent_file_path(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "kiro")
        assert cfg["agent_file"]["path"] == "~/.kiro/agents/test-agent.json"

    def test_agent_content_structure(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "kiro")
        content = cfg["agent_file"]["content"]
        assert content["name"] == "test-agent"
        assert "You are helpful." in content["prompt"]
        assert "Agent Specialization" in content["prompt"]
        assert content["model"] is None  # Kiro uses auto model selection
        assert "mcpServers" in content
        assert "hooks" in content

    def test_hooks_contain_required_events(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "kiro")
        hooks = cfg["agent_file"]["content"]["hooks"]
        for event in ("agentSpawn", "userPromptSubmit", "preToolUse", "postToolUse", "stop"):
            assert event in hooks

    def test_no_steering_file_generated(self):
        """Prompt lives in agent JSON only — no redundant steering file."""
        agent = _make_agent(prompt="Do the thing")
        cfg = generate_agent_config(agent, "kiro")
        assert "steering_file" not in cfg

    def test_description_truncated_to_200(self):
        agent = _make_agent(description="x" * 300)
        cfg = generate_agent_config(agent, "kiro")
        assert len(cfg["agent_file"]["content"]["description"]) == 200

    def test_tools_include_wildcard(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "kiro")
        tools = cfg["agent_file"]["content"]["tools"]
        assert "*" in tools

    def test_kiro_native_schema_fields(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "kiro")
        content = cfg["agent_file"]["content"]
        assert content["toolAliases"] == {}
        assert content["allowedTools"] == []
        assert content["toolsSettings"] == {}
        assert isinstance(content["resources"], list)
        assert any("AGENTS.md" in r for r in content["resources"])


# ═══════════════════════════════════════════════════════════════════
# 7. generate_agent_config — Gemini CLI
# ═══════════════════════════════════════════════════════════════════


class TestGenerateGemini:
    def test_rules_path(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini-cli")
        assert cfg["rules_file"]["path"] == "GEMINI.md"

    def test_mcp_path(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini-cli")
        assert cfg["mcp_config"]["path"] == ".gemini/settings.json"

    def test_gemini_underscore_alias(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini_cli")
        assert cfg["rules_file"]["path"] == "GEMINI.md"

    def test_otlp_env_present(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "gemini-cli")
        assert "otlp_env" in cfg


# ═══════════════════════════════════════════════════════════════════
# 8. generate_agent_config — Codex
# ═══════════════════════════════════════════════════════════════════


class TestGenerateCodex:
    def test_rules_path(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "codex")
        assert cfg["rules_file"]["path"] == "AGENTS.md"

    def test_mcp_config_present(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "codex")
        assert "mcp_config" in cfg
        assert cfg["mcp_config"]["path"] == "~/.codex/config.toml"
        assert "mcp.servers" in cfg["mcp_config"]["content"]

    def test_mcp_config_empty_servers(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "codex")
        assert cfg["mcp_config"]["content"]["mcp.servers"] == {}

    def test_content_not_empty(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "codex")
        assert len(cfg["rules_file"]["content"]) > 0


# ═══════════════════════════════════════════════════════════════════
# 9. generate_agent_config — Copilot
# ═══════════════════════════════════════════════════════════════════


class TestGenerateCopilot:
    def test_rules_path(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "copilot")
        assert cfg["rules_file"]["path"] == ".github/copilot-instructions.md"

    def test_mcp_config_present(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "copilot")
        assert "mcp_config" in cfg
        assert cfg["mcp_config"]["path"] == ".vscode/mcp.json"

    def test_mcp_config_uses_servers_key(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "copilot")
        assert "servers" in cfg["mcp_config"]["content"]

    def test_content_not_empty(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "copilot")
        assert len(cfg["rules_file"]["content"]) > 0

    def test_external_mcps_get_type_stdio(self):
        ext = [{"name": "my-srv", "command": "npx", "args": ["-y", "my-srv"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "copilot")
        entry = cfg["mcp_config"]["content"]["servers"]["my-srv"]
        assert entry["type"] == "stdio"
        assert entry["command"] == "observal-shim"
        assert isinstance(entry["args"], list)

    def test_env_vars_preserved(self):
        ext = [{"name": "my-srv", "command": "npx", "args": [], "env": {"API_KEY": "secret"}}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "copilot")
        entry = cfg["mcp_config"]["content"]["servers"]["my-srv"]
        assert entry["env"]["API_KEY"] == "secret"
        assert entry["env"]["OBSERVAL_AGENT_ID"] == str(agent.id)

    def test_scope_is_project(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "copilot")
        assert cfg["scope"] == "project"

    def test_no_mcpservers_key(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "copilot")
        assert "mcpServers" not in cfg["mcp_config"]["content"]


# ═══════════════════════════════════════════════════════════════════
# 10. generate_agent_config — External MCPs
# ═══════════════════════════════════════════════════════════════════


class TestExternalMcps:
    def test_external_mcps_appear_in_cursor_config(self):
        ext = [{"name": "ext-server", "command": "npx", "args": ["-y", "ext"]}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "cursor")
        servers = cfg["mcp_config"]["content"]["mcpServers"]
        assert "ext-server" in servers

    def test_external_mcp_wrapped_in_shim(self):
        ext = [{"name": "ext-server", "command": "npx", "args": ["-y", "ext"], "id": "ext-id"}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "cursor")
        entry = cfg["mcp_config"]["content"]["mcpServers"]["ext-server"]
        assert entry["command"] == "observal-shim"
        assert "--mcp-id" in entry["args"]
        assert "ext-id" in entry["args"]

    def test_external_mcp_string_args_split(self):
        ext = [{"name": "srv", "command": "node", "args": "serve.js --port 3000"}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "cursor")
        entry = cfg["mcp_config"]["content"]["mcpServers"]["srv"]
        assert "serve.js" in entry["args"]
        assert "--port" in entry["args"]
        assert "3000" in entry["args"]

    def test_external_mcp_env_preserved(self):
        ext = [{"name": "srv", "command": "npx", "args": [], "env": {"API_KEY": "secret"}}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "cursor")
        entry = cfg["mcp_config"]["content"]["mcpServers"]["srv"]
        assert entry["env"]["API_KEY"] == "secret"

    def test_external_mcp_with_empty_name_skipped(self):
        ext = [{"name": "", "command": "npx", "args": []}]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "cursor")
        assert len(cfg["mcp_config"]["content"]["mcpServers"]) == 0

    def test_agent_id_injected_into_all_mcp_entries(self):
        ext = [
            {"name": "srv-a", "command": "npx", "args": []},
            {"name": "srv-b", "command": "node", "args": ["s.js"]},
        ]
        agent = _make_agent(external_mcps=ext)
        cfg = generate_agent_config(agent, "cursor")
        servers = cfg["mcp_config"]["content"]["mcpServers"]
        for name in ("srv-a", "srv-b"):
            assert servers[name]["env"]["OBSERVAL_AGENT_ID"] == str(agent.id)


# ═══════════════════════════════════════════════════════════════════
# 11. generate_agent_config — MCP listings with Claude Code shim fallback
# ═══════════════════════════════════════════════════════════════════


class TestMcpListingClaudeCodeFallback:
    def test_builds_shim_entry_when_generate_config_lacks_mcpservers(self):
        """When generate_config returns shell commands (no mcpServers key),
        the Claude Code path should build shim entries directly."""
        comp_id = uuid.uuid4()
        listing = MagicMock()
        listing.name = "my-mcp"
        listing.id = comp_id

        comp = _make_component("mcp", comp_id)
        agent = _make_agent(components=[comp])

        # Mock generate_config to return a shell-command dict (no mcpServers)
        from unittest.mock import patch

        with patch(
            "services.agent_config_generator.generate_config",
            return_value={"command": "observal-shim", "args": ["--mcp-id", str(comp_id)]},
        ):
            cfg = generate_agent_config(
                agent,
                "claude-code",
                mcp_listings={comp_id: listing},
            )

        content = cfg["rules_file"]["content"]
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1])
        assert "mcpServers" in fm
        assert "my-mcp" in fm["mcpServers"]
        assert len(cfg["mcp_setup_commands"]) == 1


# ═══════════════════════════════════════════════════════════════════
# 12. generate_agent_config — name sanitization in output
# ═══════════════════════════════════════════════════════════════════


class TestNameSanitizationInOutput:
    def test_special_chars_sanitized_in_claude_code_path(self):
        agent = _make_agent(name="my agent v2!")
        cfg = generate_agent_config(agent, "claude-code")
        path = cfg["rules_file"]["path"]
        assert " " not in path
        assert "!" not in path

    def test_special_chars_sanitized_in_kiro_path(self):
        agent = _make_agent(name="my agent v2!")
        cfg = generate_agent_config(agent, "kiro")
        path = cfg["agent_file"]["path"]
        assert " " not in path


# ═══════════════════════════════════════════════════════════════════
# 13. Agent Builder — generate_ide_agent_files (manifest-based)
# ═══════════════════════════════════════════════════════════════════


class TestBuilderClaudeCode:
    def test_path_under_agents(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "claude-code")
        paths = [f.path for f in result.files]
        assert any(".claude/agents/" in p for p in paths)

    def test_yaml_frontmatter_present(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "claude-code")
        md_file = next(f for f in result.files if f.format == "markdown")
        content = md_file.content
        assert content.startswith("---\n")
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1])
        assert fm["name"] == "test-agent"

    def test_mcpservers_in_frontmatter_when_mcps_present(self):
        manifest = _make_manifest(
            mcps=[ManifestComponent(name="my-srv", version="1.0.0", git_url="https://example.com")]
        )
        result = generate_ide_agent_files(manifest, "claude-code")
        md_file = next(f for f in result.files if f.format == "markdown")
        parts = md_file.content.split("---", 2)
        fm = yaml.safe_load(parts[1])
        assert "mcpServers" in fm
        assert "my-srv" in fm["mcpServers"]

    def test_setup_commands_generated(self):
        manifest = _make_manifest(
            mcps=[ManifestComponent(name="my-srv", version="1.0.0", git_url="https://example.com")]
        )
        result = generate_ide_agent_files(manifest, "claude-code")
        assert len(result.setup_commands) == 1
        assert result.setup_commands[0][:4] == ["claude", "mcp", "add", "my-srv"]

    def test_env_contains_telemetry_vars(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "claude-code")
        assert "CLAUDE_CODE_ENABLE_TELEMETRY" in result.env


class TestBuilderCursor:
    def test_files_include_rules_and_mcp_json(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "cursor")
        paths = [f.path for f in result.files]
        assert any(".cursor/rules/" in p for p in paths)
        assert any("mcp.json" in p for p in paths)


class TestBuilderVscode:
    def test_files_include_rules_and_mcp_json(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "vscode")
        paths = [f.path for f in result.files]
        assert any(".vscode/rules/" in p for p in paths)
        assert any("mcp.json" in p for p in paths)


class TestBuilderKiro:
    def test_json_agent_file(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "kiro")
        json_file = next(f for f in result.files if f.format == "json")
        assert "~/.kiro/agents/" in json_file.path
        assert json_file.content["name"] == "test-agent"

    def test_tools_include_wildcard(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "kiro")
        json_file = next(f for f in result.files if f.format == "json")
        tools = json_file.content["tools"]
        assert "*" in tools


class TestBuilderGemini:
    def test_rules_path(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "gemini-cli")
        paths = [f.path for f in result.files]
        assert "GEMINI.md" in paths


class TestBuilderCodex:
    def test_rules_path(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "codex")
        paths = [f.path for f in result.files]
        assert "AGENTS.md" in paths

    def test_codex_only_agents_md_without_otlp_url(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "codex")
        paths = [f.path for f in result.files]
        # Without explicit OTLP URL, only AGENTS.md is generated
        assert "AGENTS.md" in paths
        assert len(paths) == 1


class TestBuilderCopilot:
    def test_rules_path(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "copilot")
        paths = [f.path for f in result.files]
        assert ".github/copilot-instructions.md" in paths

    def test_mcp_json_path(self):
        manifest = _make_manifest(
            mcps=[ManifestComponent(name="my-srv", version="1.0.0", git_url="https://a.com")],
        )
        result = generate_ide_agent_files(manifest, "copilot")
        paths = [f.path for f in result.files]
        assert ".vscode/mcp.json" in paths

    def test_mcp_config_uses_servers_key(self):
        manifest = _make_manifest(
            mcps=[ManifestComponent(name="my-srv", version="1.0.0", git_url="https://a.com")],
        )
        result = generate_ide_agent_files(manifest, "copilot")
        mcp_file = next(f for f in result.files if f.path == ".vscode/mcp.json")
        content = mcp_file.content
        assert "servers" in content
        assert "mcpServers" not in content

    def test_mcp_entries_have_type_stdio(self):
        manifest = _make_manifest(
            mcps=[ManifestComponent(name="my-srv", version="1.0.0", git_url="https://a.com")],
        )
        result = generate_ide_agent_files(manifest, "copilot")
        mcp_file = next(f for f in result.files if f.path == ".vscode/mcp.json")
        entry = mcp_file.content["servers"]["my-srv"]
        assert entry["type"] == "stdio"
        assert entry["command"] == "observal-shim"

    def test_no_mcp_file_when_no_mcp_components(self):
        manifest = _make_manifest()
        result = generate_ide_agent_files(manifest, "copilot")
        paths = [f.path for f in result.files]
        assert ".vscode/mcp.json" not in paths


class TestBuilderUnsupportedIde:
    def test_raises_for_unknown_ide(self):
        import pytest

        manifest = _make_manifest()
        with pytest.raises(ValueError, match="Unsupported IDE"):
            generate_ide_agent_files(manifest, "notepad")


class TestBuilderRulesMarkdown:
    def test_prompt_included_in_rules(self):
        manifest = _make_manifest(prompt="Be concise and helpful.")
        result = generate_ide_agent_files(manifest, "cursor")
        md_file = next(f for f in result.files if f.format == "markdown")
        assert "Be concise and helpful." in md_file.content

    def test_component_summaries_in_rules(self):
        manifest = _make_manifest(
            mcps=[ManifestComponent(name="srv-a", version="1.0.0", git_url="https://a.com", description="Server A")],
            skills=[ManifestComponent(name="skill-b", version="2.0.0", git_url="https://b.com", slash_command="doit")],
        )
        result = generate_ide_agent_files(manifest, "cursor")
        md_file = next(f for f in result.files if f.format == "markdown")
        assert "## MCP Servers" in md_file.content
        assert "**srv-a**" in md_file.content
        assert "## Skills" in md_file.content
        assert "**skill-b**" in md_file.content


# ═══════════════════════════════════════════════════════════════════
# Windows platform-aware Kiro config generation
# ═══════════════════════════════════════════════════════════════════

UNIX_FORBIDDEN_IN_WIN32 = ["cat |", "sed '", "$PPID", "$TERM", "$SHELL", "python3"]


class TestGenerateKiroWin32:
    """Fix checking: Windows Kiro configs must not contain Unix-only syntax."""

    def _all_hook_commands(self, cfg: dict) -> list[str]:
        """Extract all hook command strings from a Kiro agent config."""
        hooks = cfg["agent_file"]["content"]["hooks"]
        cmds = []
        for _event, entries in hooks.items():
            for entry in entries:
                if "command" in entry:
                    cmds.append(entry["command"])
        return cmds

    def test_win32_hooks_contain_no_unix_syntax(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "kiro", platform="win32")
        cmds = self._all_hook_commands(cfg)
        assert cmds, "Expected at least one hook command"
        for cmd in cmds:
            for forbidden in UNIX_FORBIDDEN_IN_WIN32:
                assert forbidden not in cmd, f"Found Unix-only '{forbidden}' in win32 hook: {cmd}"

    def test_win32_hooks_use_python_not_python3(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "kiro", platform="win32")
        cmds = self._all_hook_commands(cfg)
        for cmd in cmds:
            assert "python3" not in cmd
            assert "python " in cmd or "python -m" in cmd

    def test_win32_hooks_include_agent_name(self):
        agent = _make_agent(name="my-cool-agent")
        cfg = generate_agent_config(agent, "kiro", platform="win32")
        cmds = self._all_hook_commands(cfg)
        for cmd in cmds:
            assert "--agent-name my-cool-agent" in cmd

    def test_hooks_omit_model_flag(self):
        """Model is detected from Kiro SQLite at runtime, not baked into hook commands."""
        agent = _make_agent(model_name="claude-sonnet-4")
        cfg = generate_agent_config(agent, "kiro", platform="win32")
        cmds = self._all_hook_commands(cfg)
        for cmd in cmds:
            assert "--model" not in cmd

    def test_win32_still_has_all_hook_events(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "kiro", platform="win32")
        hooks = cfg["agent_file"]["content"]["hooks"]
        for event in ("agentSpawn", "userPromptSubmit", "preToolUse", "postToolUse", "stop"):
            assert event in hooks

    def test_win32_agent_file_path_unchanged(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "kiro", platform="win32")
        assert cfg["agent_file"]["path"] == "~/.kiro/agents/test-agent.json"


class TestGenerateKiroPreservation:
    """Preservation checking: Unix Kiro configs must be identical with or without platform."""

    def test_no_platform_matches_linux(self):
        agent = _make_agent()
        cfg_default = generate_agent_config(agent, "kiro")
        cfg_linux = generate_agent_config(agent, "kiro", platform="linux")
        assert cfg_default == cfg_linux

    def test_darwin_matches_default(self):
        agent = _make_agent()
        cfg_default = generate_agent_config(agent, "kiro")
        cfg_darwin = generate_agent_config(agent, "kiro", platform="darwin")
        assert cfg_default == cfg_darwin

    def test_empty_platform_matches_default(self):
        agent = _make_agent()
        cfg_default = generate_agent_config(agent, "kiro")
        cfg_empty = generate_agent_config(agent, "kiro", platform="")
        assert cfg_default == cfg_empty

    def test_unix_hooks_use_python_hook_scripts(self):
        agent = _make_agent()
        cfg = generate_agent_config(agent, "kiro", platform="linux")
        hooks = cfg["agent_file"]["content"]["hooks"]
        spawn_cmd = hooks["agentSpawn"][0]["command"]
        assert "python3 -m observal_cli.hooks.kiro_hook" in spawn_cmd
        assert "cat |" not in spawn_cmd
        assert "sed " not in spawn_cmd
        assert "curl" not in spawn_cmd

    def test_non_kiro_ides_unaffected_by_platform(self):
        agent = _make_agent()
        for ide in ("cursor", "vscode", "codex", "copilot"):
            cfg_default = generate_agent_config(agent, ide)
            cfg_win32 = generate_agent_config(agent, ide, platform="win32")
            assert cfg_default == cfg_win32, f"{ide} config changed with platform=win32"


class TestHookConfigGeneratorWin32:
    """Fix checking: hook_config_generator Windows output has no Unix syntax."""

    def test_win32_kiro_hook_no_unix_syntax(self):
        from services.hook_config_generator import generate_hook_telemetry_config

        listing = MagicMock()
        listing.event = "UserPromptSubmit"
        cfg = generate_hook_telemetry_config(listing, "kiro", platform="win32")
        cmd = cfg["hooks"]["userPromptSubmit"][0]["command"]
        for forbidden in UNIX_FORBIDDEN_IN_WIN32:
            assert forbidden not in cmd, f"Found Unix-only '{forbidden}' in win32 hook: {cmd}"
        assert "python " in cmd or "python -m" in cmd

    def test_win32_kiro_stop_hook_no_unix_syntax(self):
        from services.hook_config_generator import generate_hook_telemetry_config

        listing = MagicMock()
        listing.event = "Stop"
        cfg = generate_hook_telemetry_config(listing, "kiro", platform="win32")
        cmd = cfg["hooks"]["stop"][0]["command"]
        for forbidden in UNIX_FORBIDDEN_IN_WIN32:
            assert forbidden not in cmd, f"Found Unix-only '{forbidden}' in win32 hook: {cmd}"
        assert "python " in cmd or "python -m" in cmd

    def test_unix_kiro_hook_preserved(self):
        from services.hook_config_generator import generate_hook_telemetry_config

        listing = MagicMock()
        listing.event = "UserPromptSubmit"
        cfg_default = generate_hook_telemetry_config(listing, "kiro")
        cfg_linux = generate_hook_telemetry_config(listing, "kiro", platform="linux")
        assert cfg_default == cfg_linux

    def test_unix_kiro_stop_hook_preserved(self):
        from services.hook_config_generator import generate_hook_telemetry_config

        listing = MagicMock()
        listing.event = "Stop"
        cfg_default = generate_hook_telemetry_config(listing, "kiro")
        cfg_linux = generate_hook_telemetry_config(listing, "kiro", platform="linux")
        assert cfg_default == cfg_linux

    def test_non_kiro_ides_unaffected(self):
        from services.hook_config_generator import generate_hook_telemetry_config

        listing = MagicMock()
        listing.event = "PreToolUse"
        cfg_default = generate_hook_telemetry_config(listing, "claude-code")
        cfg_win32 = generate_hook_telemetry_config(listing, "claude-code", platform="win32")
        assert cfg_default == cfg_win32


class TestGetKiroDb:
    """Test platform-aware Kiro DB path resolution."""

    def test_unix_path(self):
        import unittest.mock
        from pathlib import Path

        from observal_cli.hooks.kiro_hook import _get_kiro_db

        with (
            unittest.mock.patch("observal_cli.hooks.kiro_hook.sys") as mock_sys,
            unittest.mock.patch("observal_cli.hooks.kiro_hook.os") as mock_os,
            unittest.mock.patch.object(Path, "exists", lambda self: ".local" in str(self)),
        ):
            mock_sys.platform = "linux"
            mock_os.environ.get = lambda key, default="": default
            db = _get_kiro_db()
            assert db is not None
            assert ".local" in str(db)
            assert "kiro-cli" in str(db)
            assert "data.sqlite3" in str(db)

    def test_win32_path_with_localappdata(self):
        import unittest.mock
        from pathlib import Path

        from observal_cli.hooks.kiro_hook import _get_kiro_db

        with (
            unittest.mock.patch("observal_cli.hooks.kiro_hook.sys") as mock_sys,
            unittest.mock.patch("observal_cli.hooks.kiro_hook.os") as mock_os,
            unittest.mock.patch.object(Path, "exists", return_value=True),
        ):
            mock_sys.platform = "win32"
            mock_os.environ.get = lambda key, default="": (
                "C:\\Users\\test\\AppData\\Local" if key == "LOCALAPPDATA" else default
            )
            db = _get_kiro_db()
            assert db is not None
            assert "AppData" in str(db)
            assert "kiro-cli" in str(db)
            assert "data.sqlite3" in str(db)
