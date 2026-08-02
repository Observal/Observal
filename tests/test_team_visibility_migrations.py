# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Guards for the Feature 3 team visibility migration.

Covers two things a migration review must never miss:
1. 018_team_publishing must not mutate row visibility. A bulk publish of legacy
   private rows is an irreversible data disclosure that fires on every upgrade.
2. It must refuse to drop team_id while team-owned rows exist.
"""

import ast
import importlib.util
import re
import types
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.deps import check_listing_visibility_async
from models.user import UserRole

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "observal-server" / "alembic" / "versions"
# Both halves of the original change now live in one migration, named to match the
# repo convention of NNN_slug for the file and the revision id alike.
TEAM_PUBLISHING_MIGRATION = VERSIONS_DIR / "018_team_publishing.py"
COMPONENT_SOURCE_MIGRATION = TEAM_PUBLISHING_MIGRATION

# Schema operations the migration is allowed to perform. alter_column is here
# because agents.is_private is added with a false server default and then has that
# default dropped, so new rows must state their own visibility. Every entry
# changes structure only: none of them can touch row data.
ALLOWED_SCHEMA_OPS = {"add_column", "alter_column", "create_index", "create_foreign_key"}


def _load_migration(path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _function_node(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path.name} has no function {name}")


def _called_op_methods(node: ast.AST) -> set[str]:
    calls = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            value = child.func.value
            if isinstance(value, ast.Name):
                calls.add(f"{value.id}.{child.func.attr}")
    return calls


def test_component_source_migration_only_changes_schema():
    """018_team_publishing must add columns and constraints and nothing else.

    The removed backfill flipped every is_private listing and every non public
    component source in one statement. downgrade() has no record of which rows it
    touched, so the disclosure is permanent.
    """
    calls = _called_op_methods(_function_node(COMPONENT_SOURCE_MIGRATION, "upgrade"))
    op_calls = {call for call in calls if call.startswith("op.")}
    assert op_calls == {f"op.{name}" for name in ALLOWED_SCHEMA_OPS}
    assert not any(call.startswith("sa.update") for call in calls)
    assert "op.execute" not in op_calls


def test_component_source_migration_has_no_data_mutation_sql():
    source = COMPONENT_SOURCE_MIGRATION.read_text()
    assert not re.search(r"\bUPDATE\b", source, re.IGNORECASE)
    assert "is_private=False" not in source
    assert "is_public=True" not in source


class _FakeResult:
    def __init__(self, count: int) -> None:
        self._count = count

    def scalar_one(self) -> int:
        return self._count


class _FakeConnection:
    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts

    def execute(self, clause):
        sql = str(clause)
        table = sql.split(" FROM ")[1].split(" ")[0]
        return _FakeResult(self._counts.get(table, 0))


@pytest.fixture
def team_publishing_migration(monkeypatch):
    module = _load_migration(TEAM_PUBLISHING_MIGRATION)

    def _bind(counts: dict[str, int]):
        monkeypatch.setattr(module.op, "get_bind", lambda: _FakeConnection(counts))

    return module, _bind


def test_downgrade_guard_allows_rollback_when_no_team_owns_rows(team_publishing_migration):
    module, bind = team_publishing_migration
    bind({})
    assert module._assert_no_team_owned_rows() is None


def test_downgrade_guard_blocks_rollback_while_team_owned_rows_exist(team_publishing_migration):
    module, bind = team_publishing_migration
    bind({"mcp_listings": 3, "agents": 1})
    with pytest.raises(RuntimeError) as exc:
        module._assert_no_team_owned_rows()
    message = str(exc.value)
    assert "agents=1" in message
    assert "mcp_listings=3" in message


def test_downgrade_runs_the_guard_before_dropping_anything(team_publishing_migration, monkeypatch):
    module, bind = team_publishing_migration
    bind({"skill_listings": 1})
    dropped = []
    for name in ("drop_constraint", "drop_index", "drop_column"):
        monkeypatch.setattr(module.op, name, lambda *a, _n=name, **kw: dropped.append(_n))

    with pytest.raises(RuntimeError):
        module.downgrade()
    assert dropped == []


async def test_legacy_private_row_without_team_stays_creator_only():
    """The reason 018_team_publishing needs no backfill.

    A pre teamspace row (is_private=True, team_id=None) resolves to its creator
    and to admins only, so leaving it untouched discloses nothing. A global
    reviewer is not on that list: nobody holds a team role over a personal
    listing, so there is no team-scoped review to enable.
    """
    creator_id = uuid.uuid4()
    listing = SimpleNamespace(is_private=True, team_id=None, submitted_by=creator_id, co_authors=[])
    creator = SimpleNamespace(id=creator_id, role=UserRole.user)
    stranger = SimpleNamespace(id=uuid.uuid4(), role=UserRole.user)
    reviewer = SimpleNamespace(id=uuid.uuid4(), role=UserRole.reviewer)
    admin = SimpleNamespace(id=uuid.uuid4(), role=UserRole.admin)

    class _NoQueryDb:
        async def scalar(self, *args, **kwargs):
            raise AssertionError("a null team_id must not trigger a membership query")

    db = _NoQueryDb()
    assert await check_listing_visibility_async(listing, creator, db) is True
    assert await check_listing_visibility_async(listing, stranger, db) is False
    assert await check_listing_visibility_async(listing, reviewer, db) is False
    assert await check_listing_visibility_async(listing, admin, db) is True
    assert await check_listing_visibility_async(listing, None, db) is False
