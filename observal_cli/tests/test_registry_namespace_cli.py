# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import json

from observal_cli import client, config, lockfile


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
    assert lockfile.local_registry_name("cursor", "mcp", "alice", "search") == "search"
    assert lockfile.local_registry_name("cursor", "mcp", "bob", "other") == "other"
    assert lockfile.local_registry_name("cursor", "mcp", "bob", "search") == "bob-search"
