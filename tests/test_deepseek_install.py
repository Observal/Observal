# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Agent pull uses native runtime locations and a lossless Cordis patch merge."""

import json
import shlex
import stat
from types import SimpleNamespace

import pytest

from observal_cli.cmd_pull import write_install_snippet
from observal_cli.errors import CliError
from observal_cli.harness.deepseek import DeepSeekAdapter
from observal_cli.harness_specs.deepseek_hooks_spec import EVENTS
from observal_cli.shared.deepseek_config import HOOK_ID, HOOK_NAME, MCP_NAME, read_entries


def _snippet(scope):
    return {
        "mcp_config": {
            "path": "~/.dsh/cordis.patch.yml",
            "content": [
                {
                    "insert": [
                        {
                            "id": "observal-mcp-tools",
                            "name": MCP_NAME,
                            "config": {
                                "serverName": "tools",
                                "transport": "stdio",
                                "command": "node",
                                "args": ["server.js"],
                            },
                        }
                    ]
                },
                {
                    "insert": [
                        {
                            "id": HOOK_ID,
                            "name": HOOK_NAME,
                            "config": {"configPath": "~/.dsh/observal/hooks.json"},
                        }
                    ]
                },
            ],
        },
        "hooks_config": {
            "path": "~/.dsh/observal/hooks.json",
            "content": {
                "hooks": {
                    event: [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 -m observal_cli.hooks.session_push --harness deepseek",
                                }
                            ]
                        }
                    ]
                    for event in EVENTS
                }
            },
            "merge": True,
        },
        "agent_profile": {
            "path": ("~/.dsh" if scope == "user" else ".dsh") + "/skills/observal-agent/SKILL.md",
            "content": "---\nname: observal-agent\ndescription: On-demand instructions\n---\nBody\n",
        },
    }


@pytest.mark.parametrize("scope", ["project", "user"])
def test_pull_mixed_scope_dry_run_and_native_write(tmp_path, monkeypatch, scope):
    root = tmp_path / "runtime"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("DSH_HOME", str(root))
    adapter = DeepSeekAdapter()
    snippet = _snippet(scope)
    patch = root / "cordis.patch.yml"
    hooks = root / "observal" / "hooks.json"
    expected_profile = (project / ".dsh" if scope == "project" else root) / "skills" / "observal-agent" / "SKILL.md"
    written, failed = write_install_snippet(
        snippet,
        harness="deepseek",
        adapter=adapter,
        target_dir=project,
        agent_id="id",
        is_user_scope=scope == "user",
        dry_run=True,
    )
    assert not failed
    assert [path for path, _ in written] == [str(patch), str(hooks), str(expected_profile)]
    assert not patch.exists() and not expected_profile.exists()
    # Foreign entries, comments, and executable-looking tags must survive verbatim.
    patch.parent.mkdir(parents=True)
    foreign = "# don't evaluate this\n- insert:\n  - id: user-plugin\n    name: !!js process.env.MODULE\n"
    patch.write_text(foreign)
    hooks.parent.mkdir(parents=True)
    hooks.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "foreign"}]}]}}))
    written, failed = write_install_snippet(
        snippet,
        harness="deepseek",
        adapter=adapter,
        target_dir=project,
        agent_id="id",
        is_user_scope=scope == "user",
    )
    assert not failed
    assert written[0] == (str(patch), "merged")
    assert patch.read_text().startswith(foreign)
    assert next(row for row in read_entries(patch) if row["id"] == HOOK_ID)["config"]["configPath"] == str(hooks)
    assert expected_profile.is_file()
    assert adapter.detect_hooks(root) == "installed"
    assert len([row for row in read_entries(patch) if row["id"] == "observal-mcp-tools"]) == 1
    installed_hooks = json.loads(hooks.read_text())["hooks"]
    assert len(installed_hooks) == len(EVENTS)
    assert installed_hooks["Stop"][0]["hooks"][0]["command"] == "foreign"
    write_install_snippet(
        snippet,
        harness="deepseek",
        adapter=adapter,
        target_dir=project,
        agent_id="id",
        is_user_scope=scope == "user",
    )
    assert patch.read_text().startswith(foreign)
    assert len([row for row in read_entries(patch) if row["id"] == HOOK_ID]) == 1


def test_server_generated_config_installs_without_format_translation(tmp_path, monkeypatch):
    from services.harness import generate_agent_config

    root = tmp_path / "runtime"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("DSH_HOME", str(root))
    agent = SimpleNamespace(
        id="agent-id",
        name="reviewer",
        description="Review changes",
        prompt="Check the tests.",
        components=[],
        external_mcps=[{"name": "tools", "command": "node", "args": ["server.js"]}],
        required_capabilities=[],
    )
    config = generate_agent_config(agent, "deepseek", options={"scope": "project"})
    adapter = DeepSeekAdapter()
    written, failed = write_install_snippet(
        config,
        harness="deepseek",
        adapter=adapter,
        target_dir=project,
        agent_id=agent.id,
        is_user_scope=False,
    )
    assert not failed and len(written) == 3
    assert adapter.detect_hooks(root) == "installed"
    assert [(mcp.name, mcp.command) for mcp in adapter.scan_home().mcps] == [("tools", "node")]
    skill = project / ".dsh/skills/observal-reviewer/SKILL.md"
    assert "Check the tests." in skill.read_text()
    assert not (project / "AGENTS.md").exists()


@pytest.mark.parametrize("scope", ["project", "user"])
def test_hook_scripts_follow_global_bridge_location(tmp_path, monkeypatch, scope):
    root = tmp_path / "runtime with spaces"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("DSH_HOME", str(root))
    snippet = _snippet(scope)
    raw_path = "~/.dsh/observal/scripts/check.sh"
    snippet["hooks_config"]["content"]["hooks"]["PreToolUse"].append(
        {"hooks": [{"type": "command", "command": raw_path}]}
    )
    snippet["hook_files"] = [{"path": raw_path, "content": "#!/bin/sh\necho checked\n", "executable": True}]
    written, failed = write_install_snippet(
        snippet,
        harness="deepseek",
        adapter=DeepSeekAdapter(),
        target_dir=project,
        agent_id="id",
        is_user_scope=scope == "user",
    )
    script = root / "observal/scripts/check.sh"
    assert not failed and (str(script), "created") in written
    assert script.read_text() == "#!/bin/sh\necho checked\n"
    assert script.stat().st_mode & stat.S_IXUSR
    installed = json.loads((root / "observal/hooks.json").read_text())
    command = installed["hooks"]["PreToolUse"][-1]["hooks"][0]["command"]
    assert shlex.split(command) == [str(script)]
    assert not (project / ".dsh/observal").exists()


@pytest.mark.parametrize(
    "raw_path",
    ["~/.dsh/../escape", ".dsh/../../escape", "~/.dsh/skills/../escape", "~/.dsh/observal/scripts/../escape"],
)
def test_reject_unsafe_paths_without_writes(tmp_path, monkeypatch, raw_path):
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "runtime"))
    with pytest.raises(CliError):
        write_install_snippet(
            {"agent_profile": {"path": raw_path, "content": "unsafe"}},
            harness="deepseek",
            adapter=DeepSeekAdapter(),
            target_dir=tmp_path,
            agent_id="id",
            is_user_scope=True,
        )
    assert not (tmp_path / "runtime").exists()


@pytest.mark.parametrize("subdir", ["skills", "observal/scripts"])
def test_generated_paths_do_not_follow_symlinks_outside_runtime_home(tmp_path, monkeypatch, subdir):
    root = tmp_path / "runtime"
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / subdir
    link.parent.mkdir(parents=True)
    link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("DSH_HOME", str(root))
    with pytest.raises(ValueError, match="escapes DSH_HOME"):
        DeepSeekAdapter().resolve_install_path(f"~/.dsh/{subdir}/file", tmp_path)
    assert list(outside.iterdir()) == []


def test_standalone_skill_uses_native_destination(tmp_path, monkeypatch):
    from observal_cli.cmd_skill import install_skill_registry_direct

    root = tmp_path / "runtime"
    monkeypatch.setenv("DSH_HOME", str(root))
    user = install_skill_registry_direct(
        name="sample",
        skill_md_content="---\nname: sample\ndescription: Sample\n---\n",
        harness="deepseek",
        scope="user",
        cwd=tmp_path,
    )
    project = install_skill_registry_direct(
        name="sample",
        skill_md_content="---\nname: sample\ndescription: Sample\n---\n",
        harness="deepseek",
        scope="project",
        cwd=tmp_path,
    )
    assert user == root / "skills/sample" and (user / "SKILL.md").is_file()
    assert project == tmp_path / ".dsh/skills/sample" and (project / "SKILL.md").is_file()
    assert not (tmp_path / ".agents/skills/sample").exists()


def test_invalid_existing_patch_is_not_overwritten(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    monkeypatch.setenv("DSH_HOME", str(root))
    patch = root / "cordis.patch.yml"
    patch.write_text("- insert: [unclosed\n")
    with pytest.raises(CliError):
        write_install_snippet(
            _snippet("project"),
            harness="deepseek",
            adapter=DeepSeekAdapter(),
            target_dir=tmp_path,
            agent_id="id",
            is_user_scope=False,
        )
    assert patch.read_text() == "- insert: [unclosed\n"
    assert not (root / "observal" / "hooks.json").exists()
