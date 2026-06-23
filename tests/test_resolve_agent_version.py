# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for _resolve_agent version attribution from lockfile."""

import json
from unittest.mock import patch

from observal_cli.sessions.base import _lookup_lockfile_agent, _resolve_agent


def _make_lockfile_entry(
    name: str = "my-agent",
    agent_id: str = "uuid-123",
    version: str = "1.2.0",
    directory: str = "/projects/app",
    scope: str = "project",
) -> dict:
    """Build a lockfile agent entry matching the real format from upsert_agent."""
    return {
        "name": name,
        "id": agent_id,
        "version": version,
        "pulled_at": "2026-06-17T00:00:00+00:00",
        "scope": scope,
        "directory": directory,
        "components": [
            {"type": "skill", "name": "pr-review", "id": "comp-1", "version": "1.0.0"},
        ],
    }


class TestResolveAgentVersionFromLockfile:
    """Verify that _resolve_agent enriches agent name with version from lockfile."""

    def test_env_agent_id_gets_version_from_lockfile(self):
        """Kiro per-agent hooks pass only the Observal agent UUID."""
        entry = _make_lockfile_entry(name="my-agent", agent_id="uuid-123", version="1.2.0")

        with (
            patch.dict("os.environ", {"OBSERVAL_AGENT_ID": "uuid-123"}, clear=True),
            patch("observal_cli.sessions.base._lookup_lockfile_agent_by_id", return_value=entry),
        ):
            agent_id, agent_version = _resolve_agent("", [], None, harness="kiro")

        assert agent_id == "uuid-123"
        assert agent_version == "1.2.0"

    def test_env_agent_id_missing_lockfile_returns_unattributed(self, tmp_path):
        """Unknown Kiro UUIDs must not fall back to cwd guesses."""
        with (
            patch.dict("os.environ", {"OBSERVAL_AGENT_ID": "missing-uuid"}, clear=True),
            patch("observal_cli.sessions.base._lookup_lockfile_agent_by_id", return_value=None),
            patch("observal_cli.sessions.base._lookup_lockfile_agent") as cwd_lookup,
        ):
            agent_id, agent_version = _resolve_agent(str(tmp_path), [], None, harness="kiro")

        assert agent_id is None
        assert agent_version is None
        cwd_lookup.assert_not_called()

    def test_kiro_without_env_agent_id_returns_unattributed(self, tmp_path):
        """Kiro has no JSONL agent field, so missing UUID means no attribution."""
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("observal_cli.sessions.base._lookup_lockfile_agent") as cwd_lookup,
        ):
            agent_id, agent_version = _resolve_agent(str(tmp_path), [], None, harness="kiro")

        assert agent_id is None
        assert agent_version is None
        cwd_lookup.assert_not_called()

    def test_env_var_gets_version_from_lockfile(self, tmp_path):
        """When OBSERVAL_AGENT_NAME is set, version should come from lockfile."""
        entry = _make_lockfile_entry(name="my-agent", agent_id="uuid-123", version="1.2.0", directory=str(tmp_path))

        with (
            patch.dict("os.environ", {"OBSERVAL_AGENT_NAME": "my-agent"}),
            patch("observal_cli.sessions.base._lookup_lockfile_agent", return_value=entry),
        ):
            agent_id, agent_version = _resolve_agent(str(tmp_path), [], None)

        assert agent_id == "uuid-123"
        assert agent_version == "1.2.0"

    def test_env_var_without_lockfile_returns_none_version(self):
        """When lockfile is missing, version should be None (graceful degradation)."""
        with (
            patch.dict("os.environ", {"OBSERVAL_AGENT_NAME": "my-agent"}),
            patch("observal_cli.sessions.base._lookup_lockfile_agent", return_value=None),
        ):
            agent_id, agent_version = _resolve_agent("/some/dir", [], None)

        assert agent_id == "my-agent"
        assert agent_version is None

    def test_jsonl_agent_setting_gets_version_from_lockfile(self, tmp_path):
        """When agent is resolved from JSONL, version should come from lockfile."""
        lines = [json.dumps({"type": "agent-setting", "agentSetting": "cc-agent"})]
        entry = _make_lockfile_entry(name="cc-agent", agent_id="uuid-456", version="2.0.1", directory=str(tmp_path))

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("observal_cli.sessions.base._lookup_lockfile_agent", return_value=entry),
        ):
            import os

            os.environ.pop("OBSERVAL_AGENT_NAME", None)
            agent_id, agent_version = _resolve_agent(str(tmp_path), lines, None)

        assert agent_id == "uuid-456"
        assert agent_version == "2.0.1"

    def test_lockfile_fallback_when_no_env_or_jsonl(self, tmp_path):
        """When neither env var nor JSONL match, lockfile provides both name and version."""
        entry = _make_lockfile_entry(
            name="fallback-agent", agent_id="uuid-789", version="3.0.0", directory=str(tmp_path)
        )

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("observal_cli.sessions.base._lookup_lockfile_agent", return_value=entry),
        ):
            import os

            os.environ.pop("OBSERVAL_AGENT_NAME", None)
            agent_id, agent_version = _resolve_agent(str(tmp_path), [], None)

        assert agent_id == "uuid-789"
        assert agent_version == "3.0.0"

    def test_no_sources_returns_none(self):
        """When nothing matches, returns (None, None)."""
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("observal_cli.sessions.base._lookup_lockfile_agent", return_value=None),
        ):
            import os

            os.environ.pop("OBSERVAL_AGENT_NAME", None)
            agent_id, agent_version = _resolve_agent("/empty/dir", [], None)

        assert agent_id is None
        assert agent_version is None

    def test_env_var_name_mismatch_returns_none_version(self, tmp_path):
        """When env agent name differs from lockfile name, version is None.

        We only attribute a version when the lockfile confirms the agent.
        """
        entry = _make_lockfile_entry(
            name="other-agent", agent_id="uuid-other", version="1.0.0", directory=str(tmp_path)
        )

        with (
            patch.dict("os.environ", {"OBSERVAL_AGENT_NAME": "my-agent"}),
            patch("observal_cli.sessions.base._lookup_lockfile_agent", return_value=entry),
        ):
            agent_id, agent_version = _resolve_agent(str(tmp_path), [], None)

        # Name comes from env var (not lockfile) since they don't match
        assert agent_id == "my-agent"
        # Version is None because lockfile entry doesn't match this agent
        assert agent_version is None

    def test_empty_cwd_uses_agent_name_lockfile_lookup(self):
        """When cwd is empty, per-agent hooks can still resolve the version by name."""
        entry = _make_lockfile_entry(name="my-agent", agent_id="uuid-123", version="1.2.0")

        with (
            patch.dict("os.environ", {"OBSERVAL_AGENT_NAME": "my-agent"}),
            patch("observal_cli.sessions.base._lookup_lockfile_agent", return_value=entry),
        ):
            agent_id, agent_version = _resolve_agent("", [], None)

        assert agent_id == "uuid-123"
        assert agent_version == "1.2.0"

    def test_lockfile_lookup_prefers_named_agent_over_first_directory_match(self, tmp_path):
        """Multiple agents can share a directory, so name must disambiguate."""
        data = {
            "harnesses": {
                "kiro": {
                    "agents": [
                        _make_lockfile_entry(
                            name="old-agent", agent_id="old-uuid", version="1.0.0", directory=str(tmp_path)
                        ),
                        _make_lockfile_entry(
                            name="my-agent", agent_id="new-uuid", version="1.2.0", directory=str(tmp_path)
                        ),
                    ]
                }
            }
        }

        with (
            patch("observal_cli.harness_registry.get_valid_harnesses", return_value=["kiro"]),
            patch("observal_cli.lockfile.read_lockfile", return_value=data),
        ):
            entry = _lookup_lockfile_agent(str(tmp_path), agent_name="my-agent")

        assert entry is not None
        assert entry["id"] == "new-uuid"
        assert entry["version"] == "1.2.0"

    def test_lockfile_lookup_uses_agent_name_when_cwd_does_not_match(self, tmp_path):
        """Kiro hook cwd can differ from the user-scoped lockfile directory."""
        data = {
            "harnesses": {
                "kiro": {
                    "agents": [
                        _make_lockfile_entry(
                            name="my-agent",
                            agent_id="uuid-123",
                            version="1.2.0",
                            directory=str(tmp_path / ".observal"),
                            scope="user",
                        )
                    ]
                }
            }
        }

        with (
            patch("observal_cli.harness_registry.get_valid_harnesses", return_value=["kiro"]),
            patch("observal_cli.lockfile.read_lockfile", return_value=data),
        ):
            entry = _lookup_lockfile_agent(str(tmp_path / "repo"), agent_name="my-agent")

        assert entry is not None
        assert entry["version"] == "1.2.0"
