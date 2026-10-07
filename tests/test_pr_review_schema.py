# SPDX-License-Identifier: Apache-2.0
"""Migration and metadata smoke tests without Docker."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from models import Base, Review, ReviewRevision


def test_review_schema_upgrades_twice_from_legacy_sqlite():
    engine = create_engine("sqlite://")
    legacy = [
        table
        for table in Base.metadata.sorted_tables
        if not table.name.startswith("review_") and table.name != "reviews"
    ]
    Base.metadata.create_all(engine, tables=legacy)
    path = Path(__file__).resolve().parent.parent / "observal-server/alembic/versions/031_pr_reviews.py"
    spec = importlib.util.spec_from_file_location("review_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        module.upgrade()
        module.upgrade()
        tables = set(inspect(conn).get_table_names())
        assert set(Base.metadata.tables) <= tables
        assert {"uq_reviews_subject_version"} <= {c["name"] for c in inspect(conn).get_unique_constraints("reviews")}
        assert {"uq_review_submission_draft"} <= {i["name"] for i in inspect(conn).get_indexes("review_submissions")}
        module.downgrade()
        assert "reviews" not in inspect(conn).get_table_names()
    engine.dispose()


def test_number_sequence_and_unique_revision():
    assert Review.__table__.c.number.default.name == "review_number_seq"
    assert any(c.name == "uq_review_revision_number" for c in ReviewRevision.__table__.constraints)
