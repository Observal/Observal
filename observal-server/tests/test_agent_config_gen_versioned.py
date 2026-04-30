"""Tests for versioned agent config generation (generate_all_ide_configs + lock file)."""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest
import yaml

from services.agent_config_generator import generate_all_ide_configs
from services.agent_lock_file import compute_integrity_hash, generate_lock_file

# ── Lock file tests ──────────────────────────────────────────────


class TestComputeIntegrityHash:
    def test_returns_sha256_prefixed(self):
        result = compute_integrity_hash("hello world")
        assert result.startswith("sha256-")
        assert len(result) == 7 + 64  # "sha256-" + 64 hex chars

    def test_deterministic(self):
        assert compute_integrity_hash("test") == compute_integrity_hash("test")

    def test_different_inputs_different_hashes(self):
        assert compute_integrity_hash("a") != compute_integrity_hash("b")


class TestGenerateLockFile:
    def test_produces_valid_yaml(self):
        components = [
            {"type": "mcp", "name": "fs-server", "resolved": "1.2.3", "id": "abc123", "source_sha": "deadbeef"},
            {"type": "skill", "name": "review", "resolved": "2.0.0", "id": "def456", "content": "skill content"},
        ]
        result = generate_lock_file(components)
        assert result.startswith("# Auto-generated")
        parsed = yaml.safe_load(result)
        assert parsed["lock_version"] == 1
        assert "resolved_at" in parsed
        assert len(parsed["components"]) == 2

    def test_external_component_has_source_sha(self):
        components = [{"type": "mcp", "name": "x", "resolved": "1.0.0", "id": "a", "source_sha": "abc123"}]
        result = generate_lock_file(components)
        parsed = yaml.safe_load(result)
        assert parsed["components"][0]["source_sha"] == "abc123"
        assert "integrity" not in parsed["components"][0]

    def test_inline_component_has_integrity(self):
        components = [{"type": "skill", "name": "x", "resolved": "1.0.0", "id": "a", "content": "hello"}]
        result = generate_lock_file(components)
        parsed = yaml.safe_load(result)
        assert parsed["components"][0]["integrity"].startswith("sha256-")
        assert "source_sha" not in parsed["components"][0]

    def test_empty_components(self):
        result = generate_lock_file([])
        parsed = yaml.safe_load(result)
        assert parsed["components"] == []


# ── generate_all_ide_configs tests ───────────────────────────────


def _mock_agent(name="test-agent", description="A test agent", prompt="You are helpful"):
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.name = name
    agent.description = description
    agent.prompt = prompt
    agent.components = []
    agent.external_mcps = []
    agent.required_ide_features = []
    agent.owner = "testuser"
    return agent


def _mock_version(agent, version="1.0.0", supported_ides=None):
    v = MagicMock()
    v.id = uuid.uuid4()
    v.agent_id = agent.id
    v.version = version
    v.description = agent.description
    v.prompt = agent.prompt
    v.supported_ides = supported_ides or ["claude-code", "cursor"]
    v.components = []
    v.external_mcps = []
    return v


class TestGenerateAllIdeConfigs:
    @pytest.mark.asyncio
    async def test_generates_for_target_ides(self):
        agent = _mock_agent()
        version = _mock_version(agent, supported_ides=["claude-code", "cursor"])
        result = await generate_all_ide_configs(
            agent_version=version,
            agent=agent,
            target_ides=["claude-code", "cursor"],
        )
        assert "claude-code" in result
        assert "cursor" in result
        assert "files" in result["claude-code"]
        assert "files" in result["cursor"]

    @pytest.mark.asyncio
    async def test_skips_unknown_ides(self):
        agent = _mock_agent()
        version = _mock_version(agent)
        result = await generate_all_ide_configs(
            agent_version=version,
            agent=agent,
            target_ides=["nonexistent-ide"],
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_claude_code_generates_rules_file(self):
        agent = _mock_agent()
        version = _mock_version(agent)
        result = await generate_all_ide_configs(
            agent_version=version,
            agent=agent,
            target_ides=["claude-code"],
        )
        files = result["claude-code"]["files"]
        # Should have a rules/agent file path
        assert any(".claude" in path for path in files)

    @pytest.mark.asyncio
    async def test_cursor_generates_rules_file(self):
        agent = _mock_agent()
        version = _mock_version(agent)
        result = await generate_all_ide_configs(
            agent_version=version,
            agent=agent,
            target_ides=["cursor"],
        )
        files = result["cursor"]["files"]
        assert any(".cursor" in path or ".rules" in path for path in files)

    @pytest.mark.asyncio
    async def test_deterministic_output(self):
        agent = _mock_agent()
        version = _mock_version(agent)
        r1 = await generate_all_ide_configs(agent_version=version, agent=agent, target_ides=["cursor"])
        r2 = await generate_all_ide_configs(agent_version=version, agent=agent, target_ides=["cursor"])
        assert r1 == r2

    @pytest.mark.asyncio
    async def test_uses_version_supported_ides_when_no_target(self):
        agent = _mock_agent()
        version = _mock_version(agent, supported_ides=["cursor"])
        result = await generate_all_ide_configs(
            agent_version=version,
            agent=agent,
            target_ides=None,
        )
        assert "cursor" in result

    @pytest.mark.asyncio
    async def test_kiro_generates_agent_file(self):
        agent = _mock_agent()
        version = _mock_version(agent, supported_ides=["kiro"])
        result = await generate_all_ide_configs(
            agent_version=version,
            agent=agent,
            target_ides=["kiro"],
        )
        files = result["kiro"]["files"]
        assert any(".kiro" in path for path in files)
        # Kiro content should be valid JSON
        for path, content in files.items():
            if path.endswith(".json"):
                parsed = json.loads(content)
                assert "name" in parsed
