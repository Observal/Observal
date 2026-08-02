# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Tests for public and teamspace visibility on registry listings."""

import ast
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import api.deps
from api.deps import (
    apply_registry_scope,
    apply_visibility_filter,
    check_listing_visibility_async,
    resolve_listing,
)

# ── Unit tests for the shared helpers ─────────────────────────────────────────


def _user(role="user"):
    from models.user import User, UserRole

    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = getattr(UserRole, role)
    return u


def _listing(is_private=False, team_id=None, submitted_by=None):
    m = MagicMock()
    m.is_private = is_private
    m.team_id = team_id
    m.submitted_by = submitted_by or uuid.uuid4()
    return m


def _inline_sql(statement) -> str:
    """Compile a statement to a single-line SQL string with bind values inlined."""
    return " ".join(str(statement.compile(compile_kwargs={"literal_binds": True})).split())


class TestApplyVisibilityFilter:
    def _stmt(self):
        s = MagicMock()
        s.where = MagicMock(return_value=s)
        return s

    def test_no_is_private_attr_passes_through(self):
        model = MagicMock(spec=[])
        stmt = self._stmt()
        result = apply_visibility_filter(stmt, model, None)
        stmt.where.assert_not_called()
        assert result is stmt

    def test_anonymous_sees_only_public(self):
        from models.mcp import McpListing

        stmt = self._stmt()
        apply_visibility_filter(stmt, McpListing, None)
        stmt.where.assert_called_once()

    def test_admin_sees_all(self):
        from models.mcp import McpListing

        stmt = self._stmt()
        result = apply_visibility_filter(stmt, McpListing, _user(role="admin"))
        stmt.where.assert_not_called()
        assert result is stmt

    def test_super_admin_sees_all(self):
        from models.mcp import McpListing

        stmt = self._stmt()
        result = apply_visibility_filter(stmt, McpListing, _user(role="super_admin"))
        stmt.where.assert_not_called()
        assert result is stmt

    def test_global_reviewer_is_filtered_like_a_regular_user(self):
        """A global reviewer reviews the public catalog, not other teams' private rows.

        Team-private items are reviewed inside their own teamspace by a team owner
        or team reviewer, so the global reviewer role carries no cross-team read.
        Only admins and super_admins skip the filter.
        """
        from models.mcp import McpListing

        stmt = self._stmt()
        apply_visibility_filter(stmt, McpListing, _user(role="reviewer"))
        stmt.where.assert_called_once()

    def test_regular_user_filter_applied(self):
        from models.mcp import McpListing

        stmt = self._stmt()
        apply_visibility_filter(stmt, McpListing, _user(role="user"))
        stmt.where.assert_called_once()

    def test_submitter_clause_is_restricted_to_listings_without_a_teamspace(self):
        """The own-listing shortcut never admits a team-private row.

        Team-private rows are admitted only by the membership EXISTS, so an
        ex-member who submitted the listing no longer sees it in any list.
        """
        from sqlalchemy import select

        from models.mcp import McpListing

        caller = _user()
        sql = _inline_sql(apply_visibility_filter(select(McpListing.id), McpListing, caller))

        assert f"mcp_listings.team_id IS NULL AND mcp_listings.submitted_by = '{caller.id.hex}'" in sql
        # The only other path to a private row is the correlated membership EXISTS.
        assert "mcp_listings.is_private = true AND mcp_listings.team_id IS NOT NULL AND (EXISTS" in sql


class TestApplyRegistryScope:
    """``team_id`` on a list route means "public plus this teamspace", not "only this teamspace".

    ``apply_publish_scope`` answers a different question (what an agent published
    for a target may contain) but resolves to the same predicate, which is why the
    two share an implementation. Narrowing to a single teamspace is ``?namespace=``.
    """

    def test_team_filter_keeps_public_rows(self):
        from sqlalchemy import select

        from models.mcp import McpListing

        team_id = uuid.uuid4()
        sql = _inline_sql(apply_registry_scope(select(McpListing.id), McpListing, _user(role="admin"), team_id=team_id))

        assert "mcp_listings.is_private = false" in sql
        assert f"mcp_listings.team_id = '{team_id.hex}'" in sql

    def test_team_filter_still_hides_other_teams_private_rows_from_non_members(self):
        from sqlalchemy import select

        from models.mcp import McpListing

        caller = _user()
        team_id = uuid.uuid4()
        sql = _inline_sql(apply_registry_scope(select(McpListing.id), McpListing, caller, team_id=team_id))

        # Caller visibility is applied before the teamspace filter, so the
        # membership EXISTS still gates every team-private row.
        assert "team_memberships" in sql
        assert f"team_memberships.user_id = '{caller.id.hex}'" in sql

    def test_public_only_drops_the_team_filter(self):
        from sqlalchemy import select

        from models.mcp import McpListing

        sql = _inline_sql(
            apply_registry_scope(
                select(McpListing.id), McpListing, _user(role="admin"), team_id=uuid.uuid4(), public_only=True
            )
        )

        assert "mcp_listings.is_private = false" in sql
        assert "mcp_listings.team_id =" not in sql


class TestCheckListingVisibilityAsync:
    """Detail and install routes resolve membership with a query instead of a cached list."""

    def _db(self, membership_id=None):
        db = MagicMock()
        db.scalar = AsyncMock(return_value=membership_id)
        return db

    @pytest.mark.asyncio
    async def test_public_listing_needs_no_membership_query(self):
        db = self._db()
        assert await check_listing_visibility_async(_listing(is_private=False), _user(), db) is True
        db.scalar.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_private_hidden_from_anonymous(self):
        db = self._db(membership_id=uuid.uuid4())
        assert await check_listing_visibility_async(_listing(is_private=True), None, db) is False
        db.scalar.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_private_visible_to_team_member(self):
        listing = _listing(is_private=True, team_id=uuid.uuid4())
        assert await check_listing_visibility_async(listing, _user(), self._db(uuid.uuid4())) is True

    @pytest.mark.asyncio
    async def test_private_hidden_from_non_member(self):
        listing = _listing(is_private=True, team_id=uuid.uuid4())
        assert await check_listing_visibility_async(listing, _user(), self._db(None)) is False

    @pytest.mark.asyncio
    async def test_private_hidden_when_no_team_and_not_submitter(self):
        listing = _listing(is_private=True, team_id=None)
        assert await check_listing_visibility_async(listing, _user(), self._db(uuid.uuid4())) is False

    @pytest.mark.asyncio
    async def test_private_visible_to_submitter_when_there_is_no_teamspace(self):
        user = _user()
        listing = _listing(is_private=True, team_id=None, submitted_by=user.id)
        assert await check_listing_visibility_async(listing, user, self._db(None)) is True

    @pytest.mark.asyncio
    async def test_submitter_removed_from_the_teamspace_loses_detail_access(self):
        """Publishing into a teamspace hands the item to the team, not to the submitter.

        Membership is the only grant, so this matches ``apply_visibility_filter``:
        an ex-member cannot read by id something that no longer appears in any list.
        """
        user = _user()
        listing = _listing(is_private=True, team_id=uuid.uuid4(), submitted_by=user.id)
        db = self._db(None)  # membership row was deleted

        assert await check_listing_visibility_async(listing, user, db) is False
        db.scalar.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_private_visible_to_admin_and_super_admin(self):
        listing = _listing(is_private=True, team_id=uuid.uuid4())
        assert await check_listing_visibility_async(listing, _user(role="admin"), self._db(None)) is True
        assert await check_listing_visibility_async(listing, _user(role="super_admin"), self._db(None)) is True

    @pytest.mark.asyncio
    async def test_private_hidden_from_a_global_reviewer_who_is_not_a_member(self):
        """The global reviewer role is not a cross-team read grant.

        Team-private items are reviewed inside their own teamspace, so a global
        reviewer falls back to the same membership query as any other user.
        """
        listing = _listing(is_private=True, team_id=uuid.uuid4())
        db = self._db(None)

        assert await check_listing_visibility_async(listing, _user(role="reviewer"), db) is False
        db.scalar.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_private_visible_to_a_global_reviewer_who_is_a_member(self):
        """Membership, not the global role, is what admits the reviewer."""
        listing = _listing(is_private=True, team_id=uuid.uuid4())
        assert await check_listing_visibility_async(listing, _user(role="reviewer"), self._db(uuid.uuid4())) is True


@asynccontextmanager
async def _seeded_team_private_listing(*, membership: bool):
    """Yield (session, listing, submitter) for a team-private listing the submitter published."""
    from models.base import Base
    from models.mcp import McpListing, McpValidationResult, McpVersion
    from models.team import Team, TeamMembership, TeamRole

    tables = [
        McpListing.__table__,
        McpVersion.__table__,
        McpValidationResult.__table__,
        Team.__table__,
        TeamMembership.__table__,
    ]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=tables)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        submitter = _user()
        team = Team(id=uuid.uuid4(), name="Platform", handle="platform", created_by=submitter.id)
        listing = McpListing(
            id=uuid.uuid4(),
            name="internal-mcp",
            namespace=team.handle,
            slug="internal-mcp",
            category="developer-tools",
            owner=team.handle,
            is_private=True,
            team_id=team.id,
            submitted_by=submitter.id,
            co_authors=[],
        )
        async with sessions() as session:
            session.add_all([team, listing])
            if membership:
                session.add(
                    TeamMembership(id=uuid.uuid4(), team_id=team.id, user_id=submitter.id, role=TeamRole.member)
                )
            await session.commit()

        async with sessions() as session:
            yield session, listing, submitter
    finally:
        await engine.dispose()


async def _visible_ids(session, caller):
    from sqlalchemy import select

    from models.mcp import McpListing

    stmt = apply_visibility_filter(select(McpListing.id), McpListing, caller)
    return set((await session.execute(stmt)).scalars().all())


class TestExMemberSubmitterAgainstARealDatabase:
    """The list filter and the detail helper must agree on the same row.

    These run the visibility SQL against in-memory SQLite instead of inspecting
    it, so a divergence between ``apply_visibility_filter`` and
    ``check_listing_visibility_async`` fails here rather than in production.
    """

    @pytest.mark.asyncio
    async def test_current_member_sees_the_listing_in_both_gates(self):
        async with _seeded_team_private_listing(membership=True) as (session, listing, submitter):
            assert listing.id in await _visible_ids(session, submitter)
            assert await check_listing_visibility_async(listing, submitter, session) is True

    @pytest.mark.asyncio
    async def test_ex_member_submitter_is_denied_by_the_list_filter_and_the_detail_helper(self):
        """Removing the submitter from the teamspace revokes both list and by-id reads."""
        async with _seeded_team_private_listing(membership=False) as (session, listing, submitter):
            assert await _visible_ids(session, submitter) == set()
            assert await check_listing_visibility_async(listing, submitter, session) is False


class TestGlobalReviewerAgainstARealDatabase:
    """Only admins hold a cross-team read of team-private listings.

    A global reviewer reviews the PUBLIC catalog. Team-private items are reviewed
    inside their own teamspace by a team owner or team reviewer, so routing another
    team's private titles past a reviewer who is not in that team buys nothing and
    discloses everything. Both gates are asserted together because the detail helper
    is the row-level twin of the list filter, and a fix applied to only one of them
    leaves a by-id read open.
    """

    @pytest.mark.asyncio
    async def test_global_reviewer_outside_the_team_is_denied_by_both_gates(self):
        async with _seeded_team_private_listing(membership=True) as (session, listing, _submitter):
            reviewer = _user(role="reviewer")

            assert await _visible_ids(session, reviewer) == set()
            assert await check_listing_visibility_async(listing, reviewer, session) is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["admin", "super_admin"])
    async def test_admins_still_see_the_listing_in_both_gates(self, role):
        async with _seeded_team_private_listing(membership=True) as (session, listing, _submitter):
            caller = _user(role=role)

            assert listing.id in await _visible_ids(session, caller)
            assert await check_listing_visibility_async(listing, caller, session) is True

    @pytest.mark.asyncio
    async def test_a_plain_team_member_still_sees_the_listing_in_both_gates(self):
        async with _seeded_team_private_listing(membership=True) as (session, listing, member):
            assert listing.id in await _visible_ids(session, member)
            assert await check_listing_visibility_async(listing, member, session) is True

    @pytest.mark.asyncio
    async def test_a_public_listing_stays_readable_by_the_reviewer(self):
        """The mirror case: narrowing privacy must not touch the public catalog.

        Status gating is a separate axis handled by ``may_view_unapproved``, so a
        reviewer keeps reading public rows here whatever their review state.
        """
        async with _seeded_team_private_listing(membership=True) as (session, listing, _submitter):
            listing.is_private = False
            listing.team_id = None
            session.add(listing)
            await session.commit()
            reviewer = _user(role="reviewer")

            assert listing.id in await _visible_ids(session, reviewer)
            assert await check_listing_visibility_async(listing, reviewer, session) is True


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows), first=lambda: self._rows[0] if self._rows else None)


def _row(namespace, slug, *, is_private=False, team_id=None, submitted_by=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        namespace=namespace,
        slug=slug,
        qualified_name=f"{namespace}/{slug}",
        is_private=is_private,
        team_id=team_id,
        submitted_by=submitted_by or uuid.uuid4(),
    )


class TestResolveListingAmbiguity:
    """A legacy bare name must not disclose listings the caller cannot see."""

    def _db(self, rows, membership_id=None):
        return SimpleNamespace(
            execute=AsyncMock(return_value=_Result(rows)),
            scalar=AsyncMock(return_value=membership_id),
        )

    @pytest.mark.asyncio
    async def test_ambiguous_public_names_are_reported(self):
        from models.mcp import McpListing

        rows = [_row("alice", "tool"), _row("bob", "tool")]
        with pytest.raises(HTTPException) as exc:
            await resolve_listing(McpListing, "tool", self._db(rows), current_user=_user())

        assert exc.value.status_code == 409
        assert "alice/tool" in exc.value.detail
        assert "bob/tool" in exc.value.detail

    @pytest.mark.asyncio
    async def test_ambiguity_message_omits_team_private_listings(self):
        """A non-member learns nothing about the colliding teamspace listing."""
        from models.mcp import McpListing

        rows = [
            _row("alice", "tool"),
            _row("secretteam", "tool", is_private=True, team_id=uuid.uuid4()),
            _row("otherteam", "tool", is_private=True, team_id=uuid.uuid4()),
        ]
        db = self._db(rows, membership_id=None)

        resolved = await resolve_listing(McpListing, "tool", db, current_user=_user())

        # Only one visible candidate remains, so the name is not ambiguous here.
        assert resolved is rows[0]

    @pytest.mark.asyncio
    async def test_ambiguity_between_hidden_listings_is_not_disclosed(self):
        from models.mcp import McpListing

        rows = [
            _row("secretteam", "tool", is_private=True, team_id=uuid.uuid4()),
            _row("otherteam", "tool", is_private=True, team_id=uuid.uuid4()),
        ]

        assert await resolve_listing(McpListing, "tool", self._db(rows), current_user=_user()) is None

    @pytest.mark.asyncio
    async def test_anonymous_caller_never_sees_private_choices(self):
        from models.mcp import McpListing

        rows = [_row("alice", "tool"), _row("secretteam", "tool", is_private=True, team_id=uuid.uuid4())]

        assert await resolve_listing(McpListing, "tool", self._db(rows), current_user=None) is rows[0]

    @pytest.mark.asyncio
    async def test_submitter_of_a_team_listing_is_not_told_about_it_after_removal(self):
        from models.mcp import McpListing

        user = _user()
        rows = [
            _row("alice", "tool"),
            _row("exteam", "tool", is_private=True, team_id=uuid.uuid4(), submitted_by=user.id),
        ]
        db = self._db(rows, membership_id=None)

        resolved = await resolve_listing(McpListing, "tool", db, current_user=user)

        assert resolved is rows[0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["admin", "super_admin"])
    async def test_admin_sees_every_colliding_listing(self, role):
        from models.mcp import McpListing

        rows = [_row("alice", "tool"), _row("secretteam", "tool", is_private=True, team_id=uuid.uuid4())]
        with pytest.raises(HTTPException) as exc:
            await resolve_listing(McpListing, "tool", self._db(rows), current_user=_user(role=role))

        assert exc.value.status_code == 409
        assert "secretteam/tool" in exc.value.detail

    @pytest.mark.asyncio
    async def test_global_reviewer_is_not_told_about_a_team_private_collision(self):
        """The 409 is built from what the caller may see, and a reviewer may not see this.

        A collision report that named the teamspace listing would leak the private
        canonical name to every global reviewer, which is exactly the disclosure the
        admin-only read closes.
        """
        from models.mcp import McpListing

        rows = [_row("alice", "tool"), _row("secretteam", "tool", is_private=True, team_id=uuid.uuid4())]

        resolved = await resolve_listing(McpListing, "tool", self._db(rows), current_user=_user(role="reviewer"))

        assert resolved is rows[0]

    @pytest.mark.asyncio
    async def test_qualified_name_is_never_treated_as_ambiguous(self):
        from models.mcp import McpListing

        rows = [_row("alice", "tool")]
        assert await resolve_listing(McpListing, "alice/tool", self._db(rows), current_user=None) is rows[0]


class TestEveryCallSitePassesTheCaller:
    """``current_user`` on ``resolve_listing`` means "anonymous", never "unset".

    A route that leaves it off evaluates a legacy bare-name collision as an
    anonymous caller, so the team-private half of the collision drops out and a
    name that must raise 409 for a team member silently resolves to the single
    public row. No behavioural test catches that, because every test in this file
    passes the caller explicitly, so this walks the shipped source instead.

    The parameter keeps a default because ``None`` is a real value that the
    anonymous detail routes pass on purpose. This scan is what makes omitting it
    a build failure rather than a silent downgrade.
    """

    @staticmethod
    def _call_sites():
        """Yield (label, keyword names) for every ``resolve_listing`` call under api/."""
        api_root = Path(api.deps.__file__).resolve().parent
        for path in sorted(api_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if called != "resolve_listing":
                    continue
                label = f"{path.relative_to(api_root.parent)}:{node.lineno}"
                yield label, {keyword.arg for keyword in node.keywords}

    def test_no_call_site_resolves_a_bare_name_as_an_anonymous_caller(self):
        offenders = [label for label, keywords in self._call_sites() if "current_user" not in keywords]
        assert offenders == [], "resolve_listing called without current_user at: " + ", ".join(offenders)

    def test_the_scan_actually_reaches_the_call_sites(self):
        """Guard the guard: a rename that silently empties the walk must fail here."""
        sites = list(self._call_sites())
        assert len(sites) >= 20, f"expected the api package to still hold the call sites, found {len(sites)}"
