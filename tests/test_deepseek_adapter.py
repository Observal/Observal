# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""DeepSeek native patch, skill discovery, hook activation, and isolation checks."""

import json

import pytest

from observal_cli.harness.deepseek import DeepSeekAdapter
from observal_cli.harness_specs.deepseek_hooks_spec import EVENTS, MODULE, build_hooks, hook_command
from observal_cli.shared.deepseek_config import HOOK_ID, HOOK_NAME, MCP_NAME, edit_owned_rows, read_entries


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setenv("DSH_HOME", str(root))
    return DeepSeekAdapter(), root


def test_static_entries_ignore_dynamic_js(tmp_path):
    path = tmp_path / "cordis.patch.yml"
    path.write_text(
        "# user's config must be kept verbatim\n"
        "- insert:\n"
        "  - id: foreign\n"
        "    name: other-plugin\n"
        "    config:\n"
        "      secret: !!js (() => process.env.SECRET)\n"
    )
    assert read_entries(path)[0]["config"]["secret"] is None
    incoming = [{"insert": [{"id": "observal-mcp-tools", "name": MCP_NAME, "config": {"serverName": "tools"}}]}]
    merged = edit_owned_rows(path.read_text(), incoming)
    assert path.read_text() in merged
    assert edit_owned_rows(merged, incoming) == merged
    assert "process.env.SECRET" in merged
    path.write_text("- insert: !!js (() => dynamicPlugin)\n" + path.read_text())
    assert read_entries(path)[0]["id"] == "foreign"
    with pytest.raises(ValueError):
        edit_owned_rows(path.read_text(), incoming)


def test_replacement_inside_mixed_insert_preserves_foreign_row_and_comments():
    existing = (
        "- insert:\n"
        f"  - id: {HOOK_ID}\n    name: '{HOOK_NAME}'\n"
        "  # keep foreign note\n"
        "  - id: user-plugin\n    name: other-plugin\n"
    )
    incoming = [{"insert": [{"id": HOOK_ID, "name": HOOK_NAME, "config": {"configPath": "/tmp/hooks.json"}}]}]
    merged = edit_owned_rows(existing, incoming)
    assert "  # keep foreign note\n  - id: user-plugin\n    name: other-plugin\n" in merged
    assert merged.count("id: observal-hooks") == 1
    assert edit_owned_rows(merged, incoming) == merged


@pytest.mark.parametrize(
    "original",
    [
        f"[{{insert: [{{id: {HOOK_ID}, name: '{HOOK_NAME}'}}]}}, {{insert: [{{id: foreign, name: other-plugin}}]}}]\n",
        "- insert:\n  - id: foreign\n    name: other-plugin\n...\n",
    ],
)
def test_reject_unsupported_patch_structure_without_writes(installed, original):
    adapter, root = installed
    root.mkdir()
    patch = root / "cordis.patch.yml"
    patch.write_text(original)
    if original.startswith("["):
        assert [row["id"] for row in read_entries(patch)] == [HOOK_ID, "foreign"]
    incoming = [
        {"insert": [{"id": HOOK_ID, "name": HOOK_NAME, "config": {"configPath": "~/.dsh/observal/hooks.json"}}]}
    ]
    with pytest.raises(ValueError):
        adapter.write_mcp_config(patch, incoming)
    assert patch.read_text() == original


def test_cleanup_retains_comments_with_an_empty_patch_sequence(installed):
    adapter, root = installed
    adapter.patch_hooks(dry_run=False)
    patch = root / "cordis.patch.yml"
    patch.write_text("# retain this comment\n" + patch.read_text())
    assert adapter.cleanup_hooks(dry_run=False)
    assert patch.read_text() == "# retain this comment\n[]\n"
    assert read_entries(patch) == []
    assert not adapter.cleanup_hooks(dry_run=False)


def test_reject_malformed_ambiguous_and_spoofed_patches():
    with pytest.raises(ValueError):
        edit_owned_rows("- insert: [", [])
    with pytest.raises(ValueError):
        edit_owned_rows("- insert:\n  - id: x\n    id: y\n", [])
    with pytest.raises(ValueError):
        edit_owned_rows(f"- insert:\n  - id: {HOOK_ID}\n    name: foreign\n", [])
    with pytest.raises(ValueError):
        edit_owned_rows("- insert:\n  - id: observal-mcp-a\n    name: wrong-plugin\n", [])


def test_scans_user_and_profile_patches_without_claiming_project_activation(installed, tmp_path):
    adapter, root = installed
    root.mkdir()
    (root / "cordis.patch.yml").write_text(
        f"- insert:\n  - id: user-mcp\n    name: '{MCP_NAME}'\n"
        "    config: {serverName: user, transport: stdio, command: node, args: [x]}\n"
    )
    profile = root / "profiles" / "headless"
    profile.mkdir(parents=True)
    (profile / "cordis.patch.yml").write_text(
        f"- insert:\n  - id: profile-mcp\n    name: '{MCP_NAME}'\n"
        "    config: {serverName: profile, transport: streamable-http, url: 'https://example.test/mcp'}\n"
    )
    project = tmp_path / "project"
    project_patch = project / ".dsh" / "cordis.patch.yml"
    project_patch.parent.mkdir(parents=True)
    project_patch.write_text((root / "cordis.patch.yml").read_text())
    home_scan = adapter.scan_home()
    assert [(m.name, m.source) for m in home_scan.mcps] == [
        ("user", "deepseek:user"),
        ("profile", "deepseek:profile:headless (select with --profile)"),
    ]
    assert adapter.scan_project(project).mcps == []


def test_skill_discovery_requires_frontmatter_and_stays_shallow(installed, tmp_path):
    adapter, root = installed
    skill = root / "skills" / "named"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: named\ndescription: Native skill\n---\nBody\n")
    (root / "skills" / "plain.md").write_text("---\nname: plain\ndescription: Flat skill\n---\n")
    nested = root / "skills" / "nested" / "deep"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("---\nname: deep\ndescription: Deep\n---\n")
    (root / "skills" / "invalid.md").write_text("no frontmatter")
    project = tmp_path / "project"
    project_skill = project / ".agents" / "skills" / "portable"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text("---\nname: portable\ndescription: Portable\n---\n")
    assert {s.name for s in adapter.scan_home().skills} == {"named", "plain"}
    assert [(s.name, s.source) for s in adapter.scan_project(project).skills] == [
        ("portable", "deepseek:project:.agents")
    ]


def test_hook_patch_and_cleanup_are_idempotent_and_preserve_foreign_content(installed):
    adapter, root = installed
    root.mkdir()
    patch = root / "cordis.patch.yml"
    original = "# keep user note\n- insert:\n  - id: foreign\n    name: !!js myPlugin\n"
    patch.write_text(original)
    hooks = root / "observal" / "hooks.json"
    hooks.parent.mkdir()
    hooks.write_text(
        json.dumps({"custom": 1, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "foreign"}]}]}})
    )
    assert adapter.detect_hooks(root) != "installed"
    assert adapter.patch_hooks(dry_run=True)
    assert patch.read_text() == original
    assert adapter.patch_hooks(dry_run=False)
    assert adapter.detect_hooks(root) == "installed"
    assert all(event in json.loads(hooks.read_text())["hooks"] for event in EVENTS)
    assert patch.read_text().startswith(original)
    assert not adapter.patch_hooks(dry_run=False)
    assert adapter.cleanup_hooks(dry_run=True)
    assert adapter.detect_hooks(root) == "installed"
    assert adapter.cleanup_hooks(dry_run=False)
    assert not adapter.cleanup_hooks(dry_run=False)
    assert patch.read_text().startswith(original)
    assert "observal-hooks" not in patch.read_text()
    assert json.loads(hooks.read_text()) == {
        "custom": 1,
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "foreign"}]}]},
    }


def test_custom_hook_rules_are_not_duplicated_on_repeated_install(installed):
    adapter, root = installed
    incoming = build_hooks()
    custom = {"matcher": "Read", "hooks": [{"type": "command", "command": "my-custom-hook"}]}
    incoming["hooks"]["Stop"].append(custom)
    path = root / "observal" / "hooks.json"
    assert adapter.write_hook_config(path, incoming) == "created"
    assert adapter.write_hook_config(path, incoming) == "merged"
    second = path.read_text()
    assert adapter.write_hook_config(path, incoming) == "merged"
    assert path.read_text() == second
    assert json.loads(second)["hooks"]["Stop"].count(custom) == 1


def test_only_actual_session_push_invocations_are_rewritten_or_removed(installed):
    adapter, _ = installed
    stale = "/old/venv/bin/python3 -m observal_cli.hooks.session_push --harness deepseek"
    echo = f"echo -m {MODULE} --harness deepseek"
    malformed = f"python3 -m {MODULE} --harness 'deepseek"
    content = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {"type": "command", "command": echo},
                        {"type": "command", "command": malformed},
                        {"type": "command", "command": stale},
                    ]
                }
            ]
        }
    }
    rewritten = adapter.rewrite_hooks(content, agent_id="unused")
    assert [handler["command"] for handler in rewritten["hooks"]["Stop"][0]["hooks"]] == [
        echo,
        malformed,
        hook_command(),
    ]
    assert content["hooks"]["Stop"][0]["hooks"][2]["command"] == stale
    cleaned = adapter._merge_hooks(content, {"hooks": {}})
    assert [handler["command"] for handler in cleaned["hooks"]["Stop"][0]["hooks"]] == [echo, malformed]
    merged = adapter._merge_hooks(content, build_hooks())
    assert [handler["command"] for handler in merged["hooks"]["Stop"][0]["hooks"]] == [echo, malformed]
    assert merged["hooks"]["Stop"][1]["hooks"][0]["command"] == hook_command()


def test_hook_detection_requires_both_bridge_and_commands(installed):
    adapter, root = installed
    root.mkdir()
    hooks = root / "observal" / "hooks.json"
    hooks.parent.mkdir()
    hooks.write_text(json.dumps(build_hooks()))
    assert adapter.detect_hooks(root) == "partial"
    (root / "cordis.patch.yml").write_text(
        f"- insert:\n  - id: {HOOK_ID}\n    name: '{HOOK_NAME}'\n    config: {{configPath: {str(hooks)!r}}}\n"
    )
    assert adapter.detect_hooks(root) == "installed"
    scoped = build_hooks()
    scoped["hooks"]["Stop"][0]["matcher"] = "some-tool-only"
    hooks.write_text(json.dumps(scoped))
    assert adapter.detect_hooks(root) == "partial"
    hooks.write_text(json.dumps({"hooks": {"Stop": []}}))
    assert adapter.detect_hooks(root) == "partial"


def test_runtime_home_and_bundled_skill_plan(installed, tmp_path):
    adapter, root = installed
    assert not adapter.is_installed(tmp_path / "other-home")
    root.mkdir()
    assert adapter.is_installed()
    assert adapter.resolve_home_dir() == root
    assert adapter.plan_bundled_skill_install("observal", tmp_path, frozenset()).target == (
        root / "skills" / "observal" / "SKILL.md"
    )
    assert adapter.skill_install_destination("native", "user", tmp_path) == root / "skills" / "native"
    assert adapter.skill_install_destination("native", "project", tmp_path) == tmp_path / ".dsh/skills/native"
    assert not adapter.is_session_final({"hook_event_name": "SubagentStop"})
    assert adapter.defer_session_delivery()
