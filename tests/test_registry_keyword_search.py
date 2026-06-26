# SPDX-License-Identifier: AGPL-3.0-only

from sqlalchemy import Column, MetaData, String, Table, create_engine, insert, select

from api.search import keyword_search


def _rows_for(query: str, descriptions: list[str]) -> list[str]:
    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    items = Table("items", meta, Column("name", String), Column("description", String))
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(items), [{"name": f"item-{i}", "description": d} for i, d in enumerate(descriptions)])
        where, rank = keyword_search(query, [items.c.name, items.c.description], name_field=items.c.name)
        assert where is not None and rank is not None
        return [r.description for r in conn.execute(select(items).where(where).order_by(rank.desc())).all()]


def test_incident_resolution_matches_incident_response_description():
    rows = _rows_for(
        "incident resolution",
        ["On-call incident response and debugging", "Frontend component builder"],
    )

    assert rows == ["On-call incident response and debugging"]


def test_frontend_design_matches_related_skill_description_without_phrase():
    rows = _rows_for(
        "frontend design",
        ["Build accessible frontend components from design systems", "On-call incident response"],
    )

    assert rows == ["Build accessible frontend components from design systems"]
