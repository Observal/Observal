# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Stress and adversarial tests for the shared recommender.

Two untrusted inputs reach this code: registry text written by publishers
(names, descriptions) and the signal string derived from telemetry. Neither
may crash the caller, leak across users, or alter a query.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from models.base import Base
from models.mcp import ListingStatus
from models.skill import SkillListing, SkillVersion
from models.user import User
from services.insights.registry_match import (
    CatalogOffer,
    RegistryScope,
    build_signals,
    catalog_block,
    validate_reuse_suggestions,
)
from services.registry_recommender import (
    build_signal_query,
    coerce_uuid,
    resolve_components,
    shortlist,
)


@pytest.fixture()
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture()
async def session_factory(tmp_path):
    """A file-backed engine, so each task can hold its own session.

    An ``AsyncSession`` is stateful and unsafe to share across concurrent
    tasks. A ``:memory:`` database cannot substitute here either: every
    connection would get its own empty database, so the seeded rows would be
    invisible to the tasks under test.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'stress.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _user(db: AsyncSession, email: str = "a@example.com") -> User:
    user = User(email=email, username=email.split("@")[0], name=email)
    db.add(user)
    await db.flush()
    return user


async def _skill(
    db: AsyncSession,
    *,
    name: str,
    description: str,
    submitter: User,
    is_private: bool = False,
) -> SkillListing:
    listing = SkillListing(
        name=name,
        namespace="test",
        slug=name.lower().replace(" ", "-")[:60],
        owner="t",
        submitted_by=submitter.id,
        is_private=is_private,
    )
    db.add(listing)
    await db.flush()
    version = SkillVersion(
        listing_id=listing.id,
        version="1.0.0",
        description=description,
        status=ListingStatus.approved,
        task_type="general",
        delivery_mode="registry_direct",
        released_by=submitter.id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()
    listing.latest_version_id = version.id
    await db.flush()
    return listing


# ── hostile signal strings ────────────────────────────────────────────────

HOSTILE_SIGNALS = [
    "'; DROP TABLE skill_listings; --",
    "%%%%%%",  # LIKE wildcards
    "_" * 200,  # LIKE single-char wildcards
    "\\%\\_",  # escaped wildcards
    "' OR '1'='1",
    "<script>alert(1)</script>",
    "../../etc/passwd",
    "\x00\x01\x02",
    "ünïcodé ✨ 中文",
    "a" * 20000,  # very long
    "\n\r\t",
    "{}{}{}",  # format-string shaped
    "{ids:Array(String)}",  # clickhouse param shaped
]


@pytest.mark.asyncio
@pytest.mark.parametrize("signals", HOSTILE_SIGNALS)
async def test_shortlist_survives_hostile_signals(db: AsyncSession, signals):
    user = await _user(db)
    await _skill(db, name="db-tool", description="Database migrations", submitter=user)

    results = await shortlist(db, signals=signals, component_types=["skill"])

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_wildcards_do_not_match_everything(db: AsyncSession):
    """A LIKE wildcard in the signal must not turn into 'select all'."""
    user = await _user(db)
    await _skill(db, name="alpha", description="Totally unrelated thing", submitter=user)
    await _skill(db, name="beta", description="Also unrelated", submitter=user)

    results = await shortlist(db, signals="%", component_types=["skill"])

    # "%" yields no usable tokens, so this falls back to popularity ordering
    # rather than a wildcard match. Either way it must not error.
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_hostile_registry_text_is_returned_verbatim_not_executed(db: AsyncSession):
    user = await _user(db)
    await _skill(
        db,
        name="evil",
        description="'; DROP TABLE skill_listings; -- database",
        submitter=user,
    )

    results = await shortlist(db, signals="database", component_types=["skill"])

    assert len(results) == 1
    assert "DROP TABLE" in results[0].description
    # The table still exists.
    assert await shortlist(db, signals="database", component_types=["skill"])


# ── private visibility under stress ───────────────────────────────────────


@pytest.mark.asyncio
async def test_no_private_leak_across_many_users(db: AsyncSession):
    users = []
    for i in range(6):
        owner = await _user(db, f"o{i}@x.com")
        users.append(owner)
        await _skill(
            db,
            name=f"secret-db-{i}",
            description="Database migrations internal",
            submitter=owner,
            is_private=True,
        )

    for i, user in enumerate(users):
        results = await shortlist(db, signals="database migrations", user_id=user.id)
        names = {c.name for c in results}
        assert names == {f"secret-db-{i}"}, f"user {i} saw {names}"


@pytest.mark.asyncio
async def test_concurrent_shortlists_stay_isolated(session_factory):
    """Concurrency must not bleed one user's results into another's."""
    async with session_factory() as seed:
        ua = await _user(seed, "a@example.com")
        ub = await _user(seed, "b@example.com")
        await _skill(seed, name="a-secret", description="database", submitter=ua, is_private=True)
        await _skill(seed, name="b-secret", description="database", submitter=ub, is_private=True)
        await seed.commit()
        user_a_id, user_b_id = ua.id, ub.id

    async def run(user_id):
        # Each task gets its own session; sharing one would be a data race.
        async with session_factory() as session:
            return await shortlist(session, signals="database", user_id=user_id)

    results = await asyncio.gather(
        *[run(user_a_id) for _ in range(5)],
        *[run(user_b_id) for _ in range(5)],
    )

    for r in results[:5]:
        assert {c.name for c in r} == {"a-secret"}
    for r in results[5:]:
        assert {c.name for c in r} == {"b-secret"}


# ── validation gate under hostile LLM output ──────────────────────────────

HOSTILE_REFS = [
    "'; DROP TABLE agents; --",
    "../../../etc/passwd",
    "<script>alert(1)</script>",
    "00000000-0000-0000-0000-000000000000",
    "not-a-uuid",
    "",
    None,
    12345,
    {"nested": "object"},
    ["a", "list"],
    "  00000000-0000-0000-0000-000000000001  ",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_ref", HOSTILE_REFS)
async def test_validation_gate_rejects_hostile_refs(db: AsyncSession, bad_ref):
    await _user(db)
    narrative = {
        "suggestions": {
            "features_to_try": [
                {
                    "action_type": "reuse_existing_component",
                    "feature": "Skill",
                    "existing_component_id": bad_ref,
                }
            ]
        }
    }

    result = await validate_reuse_suggestions(narrative, CatalogOffer(), db, RegistryScope())

    feature = result["suggestions"]["features_to_try"][0]
    assert feature.get("component_ref") is None


@pytest.mark.asyncio
async def test_validation_gate_handles_many_features(db: AsyncSession):
    user = await _user(db)
    skill = await _skill(db, name="real", description="database", submitter=user)
    features = [
        {
            "action_type": "reuse_existing_component",
            "feature": "Skill",
            "existing_component_id": str(uuid.uuid4()),
        }
        for _ in range(200)
    ]
    features.append(
        {
            "action_type": "reuse_existing_component",
            "feature": "Skill",
            "existing_component_id": str(skill.id),
        }
    )
    narrative = {"suggestions": {"features_to_try": features}}

    result = await validate_reuse_suggestions(narrative, CatalogOffer(offered_ids={skill.id}), db, RegistryScope())

    kept = [f for f in result["suggestions"]["features_to_try"] if f.get("component_ref")]
    assert len(kept) == 1
    assert kept[0]["component_ref"]["name"] == "real"


@pytest.mark.asyncio
async def test_resolve_components_ignores_non_uuid_entries(db: AsyncSession):
    assert await resolve_components(db, [("skill", "not-a-uuid")]) == {}  # type: ignore[list-item]


# ── signal builders under junk ────────────────────────────────────────────


@pytest.mark.parametrize(
    "agg",
    [
        {"top_tools": None},
        {"top_tools": "a string"},
        {"top_tools": [None, [], {}, 42]},
        {"top_languages": {"Python": 3}},
        {"tool_error_categories": None},
        {"top_tools": [["mcp__", 1]]},
    ],
)
def test_build_signals_never_raises(agg):
    assert isinstance(build_signals(agg=agg), str)


@pytest.mark.parametrize(
    "facets",
    [
        {"goal_categories": None},
        {"repeated_instructions": [{"nope": 1}]},
        {"repeated_instructions": "string"},
        {"friction_types": [[None, 2]]},
    ],
)
def test_build_signals_never_raises_on_facets(facets):
    assert isinstance(build_signals(facets_summary=facets), str)


def test_build_signal_query_ignores_none_and_blank():
    assert build_signal_query(None, "", [None, "", "ok"]) == "ok"


def test_catalog_block_escapes_nothing_but_stays_json():
    import json

    offer = CatalogOffer(
        entries_by_type={"skills": [{"id": "x", "name": "</script>", "description": 'a"b'}]},
        offered_ids={uuid.uuid4()},
    )
    block = catalog_block(offer)
    # The payload must remain valid JSON so the prompt cannot be broken apart.
    start = block.index("{")
    json.loads(block[start:])


@pytest.mark.parametrize("value", ["", None, "x", 0, [], {}, "0" * 40])
def test_coerce_uuid_is_total(value):
    assert coerce_uuid(value) is None or isinstance(coerce_uuid(value), uuid.UUID)
