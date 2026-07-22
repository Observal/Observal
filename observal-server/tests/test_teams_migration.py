# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Structural checks for the 017_teams migration and team models."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from models.team import Team, TeamMembership, TeamRole


def _load_migration():
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "017_teams.py"
    spec = importlib.util.spec_from_file_location("m017_teams", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_revision_chains_after_016():
    m = _load_migration()
    assert m.revision == "017_teams"
    assert m.down_revision == "016_registry_publish_loop"


def test_team_model_columns_and_uniqueness():
    cols = {c.name: c for c in Team.__table__.columns}
    assert {"id", "name", "handle", "description", "created_by", "created_at", "updated_at"} <= set(cols)
    assert cols["handle"].nullable is False

    handle_constraint = next(c for c in Team.__table__.constraints if getattr(c, "name", None) == "uq_teams_handle")
    assert [c.name for c in handle_constraint.columns] == ["handle"]
    assert any(idx.name == "ix_teams_created_by" for idx in Team.__table__.indexes)


def test_team_membership_model_columns_and_uniqueness():
    cols = {c.name: c for c in TeamMembership.__table__.columns}
    assert {"id", "team_id", "user_id", "role", "created_at"} <= set(cols)
    assert cols["role"].nullable is False

    unique = next(
        c for c in TeamMembership.__table__.constraints if getattr(c, "name", None) == "uq_team_memberships_team_user"
    )
    assert [c.name for c in unique.columns] == ["team_id", "user_id"]
    assert any(idx.name == "ix_team_memberships_user_id" for idx in TeamMembership.__table__.indexes)


def test_team_role_enum_has_owner_reviewer_member():
    assert {r.value for r in TeamRole} == {"owner", "reviewer", "member"}
