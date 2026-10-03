# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""GitHub webhook auto-sync for MCP listings.

A push to the tracked branch, or a published GitHub release, re-reads the MCP's
repository and publishes a new auto-approved version. A sync always creates a new
version and never edits an existing one, because agent lockfiles pin version
content by digest (services/agent_lock.py).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import tomllib
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from loguru import logger as optic
from sqlalchemy import select

from api.deps import get_effective_component_permission
from models.mcp import ListingStatus, McpListing, McpVersion
from models.mcp_webhook_sync import McpWebhookSync
from models.user import User
from schemas.mcp_webhook_sync import valid_ref_name
from services.agent_lock import CONTENT_FIELDS
from services.inbox import sources as inbox
from services.mcp_validator import (
    CLONE_TIMEOUT,
    _build_clone_url,
    _redact_clone_error,
    _validate_git_url,
    analyze_checkout,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SIGNATURE_HEADER = "X-Hub-Signature-256"
EVENT_HEADER = "X-GitHub-Event"

# Same shape the version routes accept: X.Y.Z with an optional prerelease suffix.
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(-[a-zA-Z0-9.]+)?$")

# Version columns carried over from the current version. CONTENT_FIELDS is what an
# agent lockfile hashes; the rest is listing metadata the next version keeps.
_CARRIED_FIELDS = (*CONTENT_FIELDS["mcp"], "supported_harnesses", "tools_schema", "mcp_validated")

_CHANGELOG_LIMIT = 4000


class SyncError(Exception):
    """A sync failed for a reason the listing owner can act on."""


class FetchError(SyncError):
    """Fetching the repository failed, which is often transient (network, a ref GitHub is still publishing)."""


@dataclass(frozen=True)
class SyncRequest:
    trigger: str  # push, release, manual
    ref: str | None  # branch or tag name; None means the repository's default branch
    changelog: str = ""


@dataclass(frozen=True)
class SyncOutcome:
    status: str  # success, skipped
    detail: str = ""
    version: str | None = None
    sha: str | None = None


# ── Webhook deliveries ───────────────────────────────────────


def generate_secret() -> str:
    return secrets.token_hex(32)


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Check GitHub's ``X-Hub-Signature-256`` header for ``body``."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def normalize_repo_url(url: str | None) -> str:
    """Reduce a repository URL to ``host/owner/repo`` so clone, html, and ssh URLs compare equal."""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("git@") and ":" in url:
        host, path = url[4:].split(":", 1)
    else:
        parsed = urlparse(url)
        host, path = parsed.hostname or "", parsed.path
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return f"{host.lower()}/{path.lower()}"


def _payload_repo_urls(payload: dict) -> set[str]:
    repo = payload.get("repository") or {}
    return {normalize_repo_url(repo.get(key)) for key in ("clone_url", "html_url", "ssh_url", "git_url")} - {""}


def tag_to_version(tag: str) -> str | None:
    """``v1.2.3`` and ``1.2.3`` become ``1.2.3``; anything else is not a version."""
    candidate = tag[1:] if tag[:1] in ("v", "V") else tag
    return candidate if _SEMVER_RE.match(candidate) else None


def plan_delivery(sync: McpWebhookSync, git_url: str, event: str, payload: dict) -> SyncRequest | str:
    """Decide what a webhook delivery asks for.

    Returns the sync to queue, or a reason the delivery is ignored. Raises
    ValueError when the delivery is for a different repository than the listing.
    """
    if event == "ping":
        return "ping received"
    if normalize_repo_url(git_url) not in _payload_repo_urls(payload):
        raise ValueError("This webhook is for a different repository than the MCP listing")

    if event == "push":
        if not sync.sync_on_push:
            return "push sync is turned off"
        ref = str(payload.get("ref") or "")
        if not ref.startswith("refs/heads/"):
            return "not a branch push"
        branch = ref.removeprefix("refs/heads/")
        tracked = sync.branch or (payload.get("repository") or {}).get("default_branch")
        if branch != tracked:
            return f"push to {branch} ignored; tracking {tracked}"
        if payload.get("deleted"):
            return "branch was deleted"
        if not valid_ref_name(branch):
            return "branch name is not supported"
        message = str((payload.get("head_commit") or {}).get("message") or "")
        return SyncRequest(trigger="push", ref=branch, changelog=message)

    if event == "release":
        if not sync.sync_on_release:
            return "release sync is turned off"
        action = payload.get("action")
        if action != "published":
            return f"release {action} ignored"
        release = payload.get("release") or {}
        if release.get("draft"):
            return "draft release ignored"
        tag = str(release.get("tag_name") or "")
        if not valid_ref_name(tag):
            return "release tag name is not supported"
        if tag_to_version(tag) is None:
            return f"release tag {tag} is not a semantic version (expected v1.2.3 or 1.2.3)"
        notes = str(release.get("body") or release.get("name") or "")
        return SyncRequest(trigger="release", ref=tag, changelog=notes)

    return f"{event} events are ignored"


def has_approved_version(listing: McpListing) -> bool:
    """Sync skips review, so it only updates a listing a reviewer has approved at least once."""
    return any(v.status == ListingStatus.approved for v in listing.versions or [])


# ── Fetching the repository ──────────────────────────────────


def _git(args: list[str], *, cwd: str | None = None) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=CLONE_TIMEOUT, env=env)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout


def _default_branch(clone_url: str) -> str:
    out = _git(["ls-remote", "--symref", clone_url, "HEAD"])
    for line in out.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            return line.removeprefix("ref: refs/heads/").removesuffix("\tHEAD")
    raise RuntimeError("could not resolve the repository's default branch")


def _fetch_checkout(git_url: str, dest: str, trigger: str, ref: str | None) -> tuple[str, str]:
    """Check out one ref of ``git_url`` into ``dest``. Returns (commit sha, ref name).

    A branch sync always fetches the branch tip at run time rather than the sha in
    the delivery, so a late job never publishes an older commit over a newer one.
    The authenticated URL is passed to fetch directly and never saved in .git/config.
    """
    clone_url = _build_clone_url(git_url)
    if trigger == "release":
        name = ref or ""
        refspec = f"refs/tags/{name}"
    else:
        name = ref or _default_branch(clone_url)
        refspec = f"refs/heads/{name}"
    _git(["init", "-q", dest])
    _git(["fetch", "-q", "--depth", "1", "--no-tags", clone_url, refspec], cwd=dest)
    _git(["checkout", "-q", "FETCH_HEAD"], cwd=dest)
    return _git(["rev-parse", "HEAD"], cwd=dest).strip(), name


def detect_declared_version(root: str) -> str | None:
    """The version the repository declares for itself, from pyproject.toml or package.json."""
    base = Path(root)
    pyproject = base / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(errors="ignore"))
            version = (data.get("project") or {}).get("version") or ((data.get("tool") or {}).get("poetry") or {}).get(
                "version"
            )
            if isinstance(version, str) and _SEMVER_RE.match(version):
                return version
        except (tomllib.TOMLDecodeError, AttributeError):
            pass
    package_json = base / "package.json"
    if package_json.is_file():
        try:
            version = json.loads(package_json.read_text(errors="ignore")).get("version")
            if isinstance(version, str) and _SEMVER_RE.match(version):
                return version
        except (json.JSONDecodeError, AttributeError):
            pass
    return None


# ── Versioning ───────────────────────────────────────────────


def _semver_key(version: str | None) -> tuple[int, int, int] | None:
    match = _SEMVER_RE.match(version or "")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def next_push_version(existing: list[str], declared: str | None) -> str:
    """The repository's declared version when it moved past every existing one, else a patch bump."""
    highest = max((key for v in existing if (key := _semver_key(v))), default=(0, 0, 0))
    declared_key = _semver_key(declared)
    if declared and declared_key and declared_key > highest:
        return declared
    major, minor, patch = highest
    return f"{major}.{minor}.{patch + 1}"


def _merge_env_vars(current: list | None, detected: list | None) -> list:
    """Keep the owner's env var entries and add names the repository now uses."""
    merged = [dict(item) for item in (current or []) if isinstance(item, dict)]
    known = {item.get("name") for item in merged}
    for item in detected or []:
        if isinstance(item, dict) and item.get("name") and item["name"] not in known:
            merged.append({"name": item["name"], "description": item.get("description", ""), "required": False})
            known.add(item["name"])
    return merged


def _changelog(trigger: str, ref: str, sha: str, notes: str) -> str:
    source = f"release {ref}" if trigger == "release" else f"{ref} at {sha[:12]}"
    header = f"Synced from GitHub {source}."
    notes = notes.strip()
    text = f"{header}\n\n{notes}" if notes else header
    return text[:_CHANGELOG_LIMIT]


def build_version(
    listing: McpListing,
    analysis: dict,
    *,
    version: str,
    trigger: str,
    ref: str,
    sha: str,
    notes: str,
    actor_id: uuid.UUID,
) -> McpVersion:
    """Snapshot the current version, then refresh what the repository now says.

    Fields the owner set by hand (command, args, image, setup steps, description)
    win over detection, matching how submit-time validation fills only blanks.
    """
    current = listing.latest_version
    snapshot = {field: deepcopy(getattr(current, field)) for field in _CARRIED_FIELDS} if current else {}
    now = datetime.now(UTC)
    ver = McpVersion(
        **snapshot,
        listing_id=listing.id,
        version=version,
        description=(current.description if current else "") or analysis.get("description") or listing.name,
        changelog=_changelog(trigger, ref, sha, notes),
        status=ListingStatus.approved,
        released_by=actor_id,
        released_at=now,
        reviewed_by=actor_id,
        reviewed_at=now,
    )
    ver.source_ref = ref
    ver.resolved_sha = sha
    if analysis.get("framework"):
        ver.framework = analysis["framework"]
    if analysis.get("tools"):
        ver.tools_schema = {
            "tools": [
                {"name": tool.get("name"), "description": tool.get("docstring") or tool.get("description") or ""}
                for tool in analysis["tools"]
                if isinstance(tool, dict) and tool.get("name")
            ]
        }
    ver.environment_variables = _merge_env_vars(ver.environment_variables, analysis.get("environment_variables"))
    # A suggested image is a guess (for example ghcr.io/<owner>/<repo>) that may not
    # exist. Its setup steps and docker run command are derived from it, so a sync
    # stores none of them; only an image the repository declares is filled in.
    if not analysis.get("docker_image_suggested"):
        for field in ("docker_image", "setup_instructions", "command", "args"):
            if analysis.get(field) and not getattr(ver, field, None):
                setattr(ver, field, analysis[field])
    if not ver.transport and ver.command:
        ver.transport = "stdio"
    return ver


# ── The sync job ─────────────────────────────────────────────


async def enqueue_sync(sync_id: uuid.UUID, request: SyncRequest) -> None:
    """Queue a sync on the arq worker. GitHub waits only 10s, and a clone can take minutes.

    Redelivered webhooks are not deduplicated here: the job skips a commit or tag
    it already published, so a retry after a failure still runs.
    """
    from services.redis import _get_arq_pool

    pool = await _get_arq_pool()
    await pool.enqueue_job("sync_mcp_webhook", str(sync_id), request.trigger, request.ref, request.changelog)


async def _existing_versions(db: AsyncSession, listing_id: uuid.UUID) -> list[McpVersion]:
    result = await db.execute(select(McpVersion).where(McpVersion.listing_id == listing_id))
    return list(result.scalars().all())


async def _sync_listing(db: AsyncSession, sync: McpWebhookSync, request: SyncRequest) -> SyncOutcome:
    listing = await db.get(McpListing, sync.listing_id)
    if listing is None:
        raise SyncError("The MCP listing no longer exists")
    if listing.status == ListingStatus.archived:
        return SyncOutcome(status="skipped", detail="The listing is archived")
    if not has_approved_version(listing):
        raise SyncError("The MCP server needs an approved version before it can sync")
    actor = await db.get(User, sync.enabled_by)
    if actor is None or get_effective_component_permission(listing, actor) != "owner":
        raise SyncError("The user who enabled sync no longer owns this listing. Turn sync off and on again.")
    git_url = listing.git_url
    if not git_url:
        raise SyncError("The listing has no git repository URL")
    url_err = _validate_git_url(git_url)
    if url_err:
        raise SyncError(url_err)

    release_version = tag_to_version(request.ref or "") if request.trigger == "release" else None
    if request.trigger == "release" and release_version is None:
        raise SyncError(f"Release tag {request.ref} is not a semantic version")

    tmp_dir = tempfile.mkdtemp(prefix="observal_mcp_sync_")
    try:
        try:
            sha, ref = await asyncio.wait_for(
                asyncio.to_thread(_fetch_checkout, git_url, tmp_dir, request.trigger, request.ref),
                timeout=CLONE_TIMEOUT,
            )
        except TimeoutError as e:
            raise FetchError(f"Fetching the repository timed out after {CLONE_TIMEOUT}s") from e
        except (RuntimeError, subprocess.SubprocessError) as e:
            raise FetchError(f"Failed to fetch the repository: {_redact_clone_error(e)}") from e

        analysis = await asyncio.to_thread(analyze_checkout, tmp_dir, git_url)
        declared = await asyncio.to_thread(detect_declared_version, tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Serialize syncs of one listing so two deliveries cannot claim the same version.
    await db.execute(select(McpWebhookSync.id).where(McpWebhookSync.id == sync.id).with_for_update())
    versions = await _existing_versions(db, listing.id)
    if request.trigger == "release":
        existing = next((v for v in versions if v.version == release_version), None)
        if existing is not None:
            return SyncOutcome(status="skipped", detail=f"Version {release_version} already exists", sha=sha)
        version = release_version
    else:
        existing = next((v for v in versions if v.resolved_sha == sha), None)
        if existing is not None:
            return SyncOutcome(
                status="skipped", detail=f"Commit {sha[:12]} is already version {existing.version}", sha=sha
            )
        version = next_push_version([v.version for v in versions], declared)

    ver = build_version(
        listing,
        analysis,
        version=version,
        trigger=request.trigger,
        ref=ref,
        sha=sha,
        notes=request.changelog,
        actor_id=actor.id,
    )
    db.add(ver)
    await db.flush()
    current = listing.latest_version
    if current is None or (_semver_key(version) or (0, 0, 0)) >= (_semver_key(current.version) or (0, 0, 0)):
        listing.latest_version_id = ver.id
    await inbox.on_publish(db, listing, subject_type="mcp", actor_id=actor.id, auto_approved=True, version=version)
    return SyncOutcome(status="success", detail=f"Published version {version}", version=version, sha=sha)


async def run_sync(sync_id: str, request: SyncRequest, *, final_attempt: bool = True) -> SyncOutcome | None:
    """Run one sync and record the result on the sync row. Commits its own session.

    When ``final_attempt`` is false, a FetchError is recorded as still queued and
    re-raised so the job can retry it.
    """
    from database import async_session

    async with async_session() as db:
        sync = await db.get(McpWebhookSync, uuid.UUID(sync_id))
        if sync is None:
            return None
        sync.last_sync_status = "syncing"
        sync.last_sync_error = None
        await db.commit()

        try:
            outcome = await _sync_listing(db, sync, request)
        except FetchError as e:
            await db.rollback()
            if not final_attempt:
                sync = await db.get(McpWebhookSync, uuid.UUID(sync_id))
                if sync is not None:
                    sync.last_sync_status = "queued"
                    sync.last_sync_error = f"{e}. Retrying."
                    await db.commit()
                raise
            outcome = None
            error = str(e)
        except SyncError as e:
            await db.rollback()
            outcome = None
            error = str(e)
        except Exception as e:
            await db.rollback()
            optic.error("mcp webhook sync {} failed: {}", sync_id, type(e).__name__)
            outcome = None
            error = "Unexpected error while syncing. Check the server logs."

        sync = await db.get(McpWebhookSync, uuid.UUID(sync_id))
        if sync is None:
            return outcome
        sync.last_synced_at = datetime.now(UTC)
        if outcome is None:
            sync.last_sync_status = "failed"
            sync.last_sync_error = error
        else:
            sync.last_sync_status = outcome.status
            sync.last_sync_error = outcome.detail if outcome.status == "skipped" else None
            if outcome.sha:
                sync.last_synced_sha = outcome.sha
            if outcome.version:
                sync.last_version = outcome.version
        await db.commit()
        optic.info("mcp webhook sync {}: {}", sync_id, sync.last_sync_status)
    if outcome is not None and outcome.status == "success":
        # Same as a reviewer approval: registry counts on the dashboard changed.
        from services.cache import invalidate_namespace

        await invalidate_namespace("dashboard")
    return outcome
