# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from sqlalchemy.dialects import postgresql

from services.user_search import analytics_in_condition, build_user_search_stmt


def test_build_user_search_stmt_uses_pg_trgm_similarity():
    sql = str(build_user_search_stmt("hsri", limit=8).compile(dialect=postgresql.dialect()))

    assert "similarity" in sql
    assert "users.username %" in sql
    assert "users.email %" in sql
    assert "users.name %" in sql


def test_build_user_search_stmt_caps_limit():
    compiled = build_user_search_stmt("hari", limit=999).compile(dialect=postgresql.dialect())

    assert 50 in compiled.params.values()


def test_analytics_in_condition_binds_a_list_parameter():
    params: dict[str, object] = {}

    condition = analytics_in_condition("actor_id", ["u1", "u2"], "actor", params)

    assert condition == "list_contains(CAST($actor_values AS VARCHAR[]), actor_id)"
    assert params == {"actor_values": ["u1", "u2"]}
