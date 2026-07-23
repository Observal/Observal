# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import json

from observal_cli import client, config, lockfile, render


def test_listings_render_the_bare_name_over_an_at_handle():
    item = {
        "name": "Task Creator",
        "namespace": "alice",
        "slug": "task-creator",
        "qualified_name": "alice/task-creator",
    }

    assert render.registry_identity(item) == ("task-creator", "alice")
    assert render.name_block(item) == "task-creator\n[not bold dim]@alice[/not bold dim]"
    assert render.name_inline(item) == "task-creator [dim]@alice[/dim]"
    # Commands still need the slash form.
    assert client.canonical_name(item) == "alice/task-creator"


def test_namespace_falls_back_to_the_qualified_name_and_degrades_without_one():
    assert render.registry_identity({"name": "x", "qualified_name": "bob/search"}) == ("search", "bob")
    assert render.registry_identity({"name": "Legacy"}) == ("Legacy", None)
    assert render.name_block({"name": "Legacy"}) == "Legacy"
    assert render.name_inline({"name": "Legacy"}) == "Legacy"


def test_dotted_namespaces_are_valid_but_flattened_in_local_install_names(tmp_path, monkeypatch):
    from observal_shared.namespace_rules import is_valid_namespace

    assert is_valid_namespace("legacy.handle")
    assert not is_valid_namespace("a..b")

    monkeypatch.setattr(config, "load", lambda: {"server_url": "https://registry.example.com"})
    monkeypatch.setattr(lockfile, "LOCKFILE_PATH", tmp_path / "lockfile.json")
    monkeypatch.setattr(lockfile, "_LOCKFILE_LOCK", tmp_path / "lockfile.lock")
    lockfile.upsert_agent(
        "kiro",
        name="tool",
        agent_id="00000000-0000-0000-0000-000000000001",
        version="1.0.0",
        namespace="alice",
        slug="tool",
        local_name="tool",
    )

    # A dot would read as a file extension once this reaches disk or a config key.
    assert lockfile.local_registry_name("kiro", "agent", "legacy.handle", "tool") == "legacy-handle-tool"


def test_qualified_reference_resolves_once(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "resolve_alias", lambda value: value)

    def fake_get(path, params=None):
        calls.append((path, params))
        return {"id": "00000000-0000-0000-0000-000000000123"}

    monkeypatch.setattr(client, "get", fake_get)
    result = client.resolve_registry_reference("agents", "alice/reviewer")
    assert result.endswith("0123")
    assert calls == [
        (
            "/api/v1/registry/resolve",
            {"type": "agent", "identifier": "alice/reviewer"},
        )
    ]


def test_uuid_and_bare_references_do_not_call_resolver(monkeypatch):
    monkeypatch.setattr(config, "resolve_alias", lambda value: value)
    monkeypatch.setattr(client, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected")))
    assert client.resolve_registry_reference("agent", "reviewer") == "reviewer"
    assert client.resolve_registry_reference("agent", "00000000-0000-0000-0000-000000000123").endswith("0123")


def test_local_name_changes_only_for_actual_same_slug_collision(tmp_path, monkeypatch):
    path = tmp_path / "lockfile.json"
    monkeypatch.setattr(config, "load", lambda: {"server_url": "https://registry.example.com/"})
    path.write_text(
        json.dumps(
            {
                "lock_version": 1,
                "harnesses": {
                    "cursor": {
                        "agents": [],
                        "standalone": [{"type": "mcp", "namespace": "alice", "slug": "search", "scope": "user"}],
                    }
                },
            }
        )
    )
    monkeypatch.setattr(lockfile, "LOCKFILE_PATH", path)
    monkeypatch.setattr(lockfile, "_LOCKFILE_LOCK", tmp_path / "lockfile.lock")
    assert lockfile.local_registry_name("cursor", "mcp", "alice", "search") == "search"
    assert lockfile.local_registry_name("cursor", "mcp", "bob", "other") == "other"
    assert lockfile.local_registry_name("cursor", "mcp", "bob", "search") == "bob-search"
    migrated = json.loads(path.read_text())
    assert migrated["lock_version"] == 2
    assert "https://registry.example.com" in migrated["registries"]


def test_v1_migration_can_preserve_previous_registry(tmp_path, monkeypatch):
    path = tmp_path / "lockfile.json"
    path.write_text(json.dumps({"lock_version": 1, "harnesses": {"kiro": {"agents": []}}}))
    monkeypatch.setattr(config, "load", lambda: {"server_url": "https://new.example.com"})
    monkeypatch.setattr(lockfile, "LOCKFILE_PATH", path)
    monkeypatch.setattr(lockfile, "_LOCKFILE_LOCK", tmp_path / "lockfile.lock")

    assert lockfile.migrate_lockfile_v1("https://old.example.com") is True
    assert set(lockfile.read_lockfile()["registries"]) == {"https://old.example.com"}


def test_nested_registries_are_isolated(tmp_path, monkeypatch):
    server = {"url": "https://one.example.com"}
    monkeypatch.setattr(config, "load", lambda: {"server_url": server["url"]})
    monkeypatch.setattr(lockfile, "LOCKFILE_PATH", tmp_path / "lockfile.json")
    monkeypatch.setattr(lockfile, "_LOCKFILE_LOCK", tmp_path / "lockfile.lock")

    lockfile.upsert_agent(
        "kiro",
        name="one",
        agent_id="00000000-0000-0000-0000-000000000001",
        version="1.0.0",
        namespace="alice",
        slug="shared",
        local_name="shared",
    )
    server["url"] = "https://two.example.com/"
    assert lockfile.local_registry_name("kiro", "agent", "alice", "shared") == "alice-shared"
    lockfile.upsert_agent(
        "kiro",
        name="two",
        agent_id="00000000-0000-0000-0000-000000000002",
        version="1.0.0",
        namespace="alice",
        slug="shared",
        local_name="alice-shared",
    )

    data = lockfile.read_lockfile()
    assert set(data["registries"]) == {"https://one.example.com", "https://two.example.com"}
    assert lockfile.get_agent_by_id("00000000-0000-0000-0000-000000000001") is None
    assert lockfile.get_agent_by_id("00000000-0000-0000-0000-000000000002")["name"] == "two"


def test_reconciliation_updates_metadata_but_keeps_installed_version(tmp_path, monkeypatch):
    from observal_cli import lockfile_reconcile

    server_url = "https://registry.example.com"
    agent_id = "00000000-0000-0000-0000-000000000001"
    monkeypatch.setattr(config, "load", lambda: {"server_url": server_url})
    monkeypatch.setattr(lockfile, "LOCKFILE_PATH", tmp_path / "lockfile.json")
    monkeypatch.setattr(lockfile, "_LOCKFILE_LOCK", tmp_path / "lockfile.lock")
    lockfile.upsert_agent(
        "kiro",
        name="old-name",
        agent_id=agent_id,
        version="1.0.0",
        namespace="old-owner",
        slug="stable-slug",
    )
    monkeypatch.setattr(
        client,
        "post",
        lambda *_args, **_kwargs: [
            {
                "type": "agent",
                "id": agent_id,
                "found": True,
                "name": "new-name",
                "namespace": "new-owner",
                "slug": "stable-slug",
                "qualified_name": "new-owner/stable-slug",
                "status": "approved",
                "latest_version": "2.0.0",
            }
        ],
    )

    plan = lockfile_reconcile.plan_lockfile_reconciliation()
    assert {change.field for change in plan.changes} == {
        "name",
        "namespace",
        "qualified_name",
        "registry_status",
    }
    plan.apply()
    entry = lockfile.get_agent_by_id(agent_id)
    assert entry["name"] == "new-name"
    assert entry["namespace"] == "new-owner"
    assert entry["qualified_name"] == "new-owner/stable-slug"
    assert entry["version"] == "1.0.0"
