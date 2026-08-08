# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""One declaration per inbox kind.

Adding a source is adding an entry to ``SPECS`` — the title, the dedupe key, the
canonical link and the exact CLI command all live together here rather than
being spelled out at each call site. Endpoints hand ``deliver()`` a subject and a
kind; they never build a title or a URL themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from models.inbox import InboxKind
from observal_shared.namespace_rules import is_valid_namespace
from services.registry_namespace import SLUG_RE

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class Subject:
    """What an item is about.

    ``namespace`` and ``slug`` produce canonical registry action links when
    they satisfy the same route rules as the web frontend.
    """

    type: str
    id: uuid.UUID | None = None
    name: str = ""
    namespace: str | None = None
    slug: str | None = None
    version: str | None = None
    team_id: uuid.UUID | None = None
    is_private: bool = False
    handle: str | None = None  # teamspaces are addressed by handle, not id


# Singular subject type to the plural the web router expects in its path or
# legacy `?type=` fallback.
_COMPONENT_TYPE_PARAM = {
    "mcp": "mcps",
    "skill": "skills",
    "hook": "hooks",
    "prompt": "prompts",
    "sandbox": "sandboxes",
}


def _canonical_parts(subject: Subject) -> tuple[str, str] | None:
    namespace = (subject.namespace or "").strip()
    slug = (subject.slug or "").strip()
    if (
        namespace == namespace.lower()
        and slug == slug.lower()
        and is_valid_namespace(namespace)
        and SLUG_RE.fullmatch(slug)
    ):
        return namespace, slug
    return None


def _registry_url(subject: Subject) -> str | None:
    """Canonical product URL with a UUID fallback for legacy identities."""
    if subject.type == "team":
        return f"/teamspaces/{subject.handle}" if subject.handle else "/teamspaces"
    if subject.type == "insight_report":
        return f"/insights/{subject.id}" if subject.id else None

    parts = _canonical_parts(subject)
    if subject.type == "agent":
        if parts:
            return f"/agents/{parts[0]}/{parts[1]}"
        return f"/agents/{subject.id}" if subject.id else None
    if plural := _COMPONENT_TYPE_PARAM.get(subject.type):
        if parts:
            return f"/components/{plural}/{parts[0]}/{parts[1]}"
        return f"/components/{subject.id}?type={plural}" if subject.id else None
    return None


def _review_url(subject: Subject) -> str:
    """Reviewers act in the queue, not on the public listing page.

    The tab is named explicitly. The review page opens on "agents" by default,
    so a link that omitted it dropped a reviewer on a tab that does not contain
    the component they were sent to look at.
    """
    tab = "agents" if subject.type == "agent" else "components"
    return f"/review?tab={tab}"


def _no_command(subject: Subject, ctx: dict[str, Any]) -> str | None:
    return None


def _review_show_command(subject: Subject, ctx: dict[str, Any]) -> str | None:
    if subject.id is None:
        return None
    suffix = " --agent" if subject.type == "agent" else ""
    return f"observal admin review show {subject.id}{suffix}"


# A pull target is a namespace/slug pair or a UUID; a harness is a registry key.
# Neither ever contains a space, a quote, or a shell metacharacter.
_SAFE_TARGET = re.compile(r"^[a-zA-Z0-9._/-]{1,128}$")
_SAFE_HARNESS = re.compile(r"^[a-zA-Z0-9._-]{1,50}$")


def _pull_command(subject: Subject, ctx: dict[str, Any]) -> str | None:
    """The upgrade command for an installed item.

    Inbox never runs this. It renders the exact command for the user to copy,
    which is precisely why the parts are validated here: the values arrive from
    a CLI-supplied report, and the product of this function is a string the web
    UI and the terminal both present as "run this". A name carrying a quote or a
    semicolon would render as a command that does something other than it reads.
    Anything that does not match is dropped rather than escaped, because a
    mangled command is worse than no command.

    ``subject.name`` is deliberately not a fallback target. It is a display
    name, and `observal pull` does not accept one.
    """
    target = f"{subject.namespace}/{subject.slug}" if subject.namespace and subject.slug else None
    if target is None and subject.id is not None:
        target = str(subject.id)
    if not target or not _SAFE_TARGET.match(target):
        return None

    harness = ctx.get("harness")
    harness_flag = ""
    if harness and _SAFE_HARNESS.match(str(harness)):
        harness_flag = f" --harness {harness}"
    return f"observal pull {target}{harness_flag}"


@dataclass(frozen=True, slots=True)
class KindSpec:
    """How one kind renders and deduplicates."""

    kind: InboxKind
    action_required: bool
    title: Callable[[Subject, dict[str, Any]], str]
    dedupe: Callable[[Subject, dict[str, Any]], str]
    url: Callable[[Subject], str | None] = _registry_url
    command: Callable[[Subject, dict[str, Any]], str | None] = _no_command
    # Items whose subject is a listing are re-checked against team membership at
    # read time. A decision addressed to its own submitter is not: it tells them
    # what happened to something they wrote, which is theirs to know regardless
    # of where the listing ended up.
    recheck_visibility: bool = True
    # Whether a redelivery of the same dedupe key resurrects a copy the
    # recipient already resolved. True fits one-shot facts that can become true
    # again (a resubmitted version re-entering review). False fits recurring
    # reports of a fact that never stopped being true: ``update_available``
    # arrives on every ``observal outdated`` run, and reopening a dismissed
    # notice each time would make dismissal meaningless.
    reopen_on_redelivery: bool = True
    # Reserved kinds are declared but have no producer: nothing in the codebase
    # delivers them yet. They exist so the enum and its migration stay stable
    # when the initiative they belong to lands, and are labelled here so
    # "declared" is never mistaken for "working". Each needs its own issue
    # settling recipients, trigger points, dedupe semantics, authorization,
    # action links and the tests that close it.
    reserved: bool = False
    subject_label: Callable[[Subject], str] = field(default=lambda s: s.name or s.type)


def _label(subject: Subject) -> str:
    return subject.name or (subject.slug or str(subject.id or "item"))


def _versioned(subject: Subject) -> str:
    return f"{_label(subject)} v{subject.version}" if subject.version else _label(subject)


SPECS: dict[InboxKind, KindSpec] = {
    InboxKind.review_requested: KindSpec(
        kind=InboxKind.review_requested,
        action_required=True,
        title=lambda s, c: f"Review requested: {_versioned(s)}",
        dedupe=lambda s, c: f"review_requested:{s.type}:{s.id}:v{s.version or '-'}",
        url=_review_url,
        command=_review_show_command,
    ),
    InboxKind.review_approved: KindSpec(
        kind=InboxKind.review_approved,
        action_required=False,
        title=lambda s, c: f"Approved: {_versioned(s)}",
        dedupe=lambda s, c: f"review_approved:{s.type}:{s.id}:v{s.version or '-'}",
        recheck_visibility=False,
    ),
    InboxKind.review_rejected: KindSpec(
        kind=InboxKind.review_rejected,
        action_required=True,
        title=lambda s, c: f"Changes needed: {_versioned(s)}",
        dedupe=lambda s, c: f"review_rejected:{s.type}:{s.id}:v{s.version or '-'}",
        recheck_visibility=False,
    ),
    InboxKind.review_comment: KindSpec(
        kind=InboxKind.review_comment,
        # RESERVED - waits on review conversations; no comment model exists yet.
        reserved=True,
        action_required=False,
        title=lambda s, c: f"New comment on {_label(s)}",
        dedupe=lambda s, c: f"review_comment:{s.type}:{s.id}:{c.get('comment_id', '-')}",
    ),
    InboxKind.change_requested: KindSpec(
        kind=InboxKind.change_requested,
        # RESERVED - waits on review conversations; distinct from review_rejected.
        reserved=True,
        action_required=True,
        title=lambda s, c: f"Changes requested on {_label(s)}",
        dedupe=lambda s, c: f"change_requested:{s.type}:{s.id}:{c.get('request_id', '-')}",
        recheck_visibility=False,
    ),
    InboxKind.team_join_requested: KindSpec(
        kind=InboxKind.team_join_requested,
        action_required=True,
        title=lambda s, c: f"Join request for {_label(s)}",
        dedupe=lambda s, c: f"team_join_requested:{s.id}:{c.get('requester_id', '-')}",
        # Owners act on requests in the teamspace's Join requests tab, not on
        # the teamspace landing page.
        url=lambda s: f"/teamspaces/{s.handle}?tab=join-requests" if s.handle else "/teamspaces",
    ),
    InboxKind.team_join_decided: KindSpec(
        kind=InboxKind.team_join_decided,
        action_required=False,
        title=lambda s, c: f"Join request {c.get('decision', 'decided')}: {_label(s)}",
        dedupe=lambda s, c: f"team_join_decided:{s.id}:{c.get('request_id', '-')}",
        # A decision addressed to the requester stays theirs to read even if it
        # was a rejection and they never became a member.
        recheck_visibility=False,
    ),
    InboxKind.team_created_pending: KindSpec(
        kind=InboxKind.team_created_pending,
        # RESERVED - waits on teamspace creation requiring approval.
        reserved=True,
        action_required=True,
        title=lambda s, c: f"Teamspace awaiting approval: {_label(s)}",
        dedupe=lambda s, c: f"team_created_pending:{s.id}",
    ),
    InboxKind.ownership_transfer: KindSpec(
        kind=InboxKind.ownership_transfer,
        # RESERVED - waits on the listing ownership-transfer flow.
        reserved=True,
        action_required=True,
        title=lambda s, c: f"Ownership transfer offered: {_label(s)}",
        dedupe=lambda s, c: f"ownership_transfer:{s.type}:{s.id}:{c.get('transfer_id', '-')}",
    ),
    InboxKind.update_available: KindSpec(
        kind=InboxKind.update_available,
        action_required=False,
        title=lambda s, c: f"Update available: {_label(s)} {c.get('current_version', '?')} → {s.version}",
        # Keyed on the new version, so a newer release is a new fact and a new
        # item rather than a duplicate of the old one.
        dedupe=lambda s, c: f"update_available:{s.type}:{s.id}:{s.version}",
        command=_pull_command,
        # Reported by the CLI about what the reporting user has installed, so
        # there is no team subject to re-check.
        recheck_visibility=False,
        # Re-reported on every run while the user stays outdated; a dismissed
        # notice must stay dismissed. A newer version is a new key anyway.
        reopen_on_redelivery=False,
    ),
    InboxKind.insight_ready: KindSpec(
        kind=InboxKind.insight_ready,
        action_required=False,
        title=lambda s, c: f"Insight report ready: {_label(s)}",
        dedupe=lambda s, c: f"insight_ready:{s.id}",
        recheck_visibility=False,
    ),
    InboxKind.system_notice: KindSpec(
        kind=InboxKind.system_notice,
        # RESERVED - helper exists in sources.on_system_notice but has no caller; operational events currently page through services/alert_evaluator.py instead.
        reserved=True,
        action_required=False,
        title=lambda s, c: str(c.get("title") or "System notice"),
        dedupe=lambda s, c: f"system_notice:{c.get('notice_id', '-')}",
        url=lambda s: None,
        recheck_visibility=False,
    ),
}


def spec_for(kind: InboxKind) -> KindSpec:
    spec = SPECS.get(kind)
    if spec is None:
        raise KeyError(f"No inbox spec registered for kind {kind!r}")
    return spec
