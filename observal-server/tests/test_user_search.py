# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from sqlalchemy.dialects import postgresql

from services.user_search import build_user_search_stmt, clickhouse_in_condition


def test_build_user_search_stmt_uses_pg_trgm_similarity():
    sql = str(build_user_search_stmt("hsri", limit=8).compile(dialect=postgresql.dialect()))

    assert "similarity" in sql
    assert "users.username %" in sql
    assert "users.email %" in sql
    assert "users.name %" in sql


def test_build_user_search_stmt_caps_limit():
    compiled = build_user_search_stmt("hari", limit=999).compile(dialect=postgresql.dialect())

    assert 50 in compiled.params.values()


def test_clickhouse_in_condition_adds_params():
    params: dict[str, str] = {}

    condition = clickhouse_in_condition("actor_id", ["u1", "u2"], "actor", params)

    assert condition == "actor_id IN ({actor_0:String}, {actor_1:String})"
    assert params == {"param_actor_0": "u1", "param_actor_1": "u2"}
