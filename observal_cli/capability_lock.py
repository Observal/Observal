# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""The capability lock: a local record of which registry resources were used, and when.

Every activation appends one line to ``~/.observal/capability_lock.jsonl``:
which resource, which exact version and digest, in which directory, from
which harness, and how it was activated. Session upload (``session_push`` and
``observal reconcile``) reads the lines that fall inside a session's harness,
directory and time window and attaches them to the session, which is how
Observal learns that a resource was actually used without any new tracking
channel. ``observal agent init --from-capabilities`` reads the same file to
turn a good session into a draft Agent.

Nothing in this file is secret: identifiers, versions, digests, paths and
timestamps only.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from observal_cli import lockfile as _lockfile

if TYPE_CHECKING:
    from collections.abc import Iterable

# Tests set this to redirect every write; production resolves the path from the
# lockfile module at call time so the existing CONFIG_DIR isolation covers it.
LOCK_PATH: Path | None = None
LOCK_FILENAME = "capability_lock.jsonl"
DEFAULT_RETENTION_DAYS = 30
MAX_LINE_BYTES = 8 * 1024

MODE_CONTEXT = "context"  # content loaded into the current session
MODE_NEXT_SESSION = "next-session"  # harness config written, effective after restart
MODES = (MODE_CONTEXT, MODE_NEXT_SESSION)


@dataclass(slots=True)
class CapabilityUse:
    ts: str  # ISO 8601, UTC
    harness: str | None
    cwd: str
    identifier: str | None  # urn:air:... when known
    kind: str  # agent | mcp | skill | hook | prompt | sandbox
    component_id: str | None  # native UUID, when known
    native_ref: str | None  # namespace/slug@version
    version: str | None
    digest: str | None
    mode: str
    source: str  # discover-cli | install | pull | gateway
    session_hint: str | None = None
    extra: dict = field(default_factory=dict)

    def to_json(self) -> str:
        payload = {k: v for k, v in asdict(self).items() if v not in (None, {}, "")}
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> CapabilityUse | None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or not data.get("ts") or not data.get("kind"):
            return None
        known = {f for f in cls.__dataclass_fields__}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            ts=str(data["ts"]),
            harness=data.get("harness"),
            cwd=str(data.get("cwd") or ""),
            identifier=data.get("identifier"),
            kind=str(data["kind"]),
            component_id=data.get("component_id"),
            native_ref=data.get("native_ref"),
            version=data.get("version"),
            digest=data.get("digest"),
            mode=str(data.get("mode") or MODE_CONTEXT),
            source=str(data.get("source") or "unknown"),
            session_hint=data.get("session_hint"),
            extra={**(data.get("extra") or {}), **extra},
        )

    @property
    def timestamp(self) -> datetime:
        return _parse_ts(self.ts)


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def default_lock_path() -> Path:
    return LOCK_PATH or (_lockfile.CONFIG_DIR / LOCK_FILENAME)


def session_hint_from_env() -> str | None:
    """The harness's own session id, when a hook exposes it in the environment."""
    for name in ("OBSERVAL_SESSION_ID", "CLAUDE_SESSION_ID", "KIRO_SESSION_ID"):
        value = os.environ.get(name)
        if value:
            return value
    return None


def record(
    *,
    kind: str,
    mode: str,
    source: str,
    harness: str | None,
    cwd: str | Path | None = None,
    identifier: str | None = None,
    component_id: str | None = None,
    native_ref: str | None = None,
    version: str | None = None,
    digest: str | None = None,
    session_hint: str | None = None,
    extra: dict | None = None,
    path: Path | None = None,
    now: datetime | None = None,
) -> CapabilityUse:
    """Append one use to the lock. Never raises on a missing config directory."""
    if mode not in MODES:
        raise ValueError(f"unknown capability mode: {mode}")
    use = CapabilityUse(
        ts=(now or _now()).isoformat(timespec="seconds").replace("+00:00", "Z"),
        harness=harness,
        cwd=str(Path(cwd or Path.cwd()).resolve()),
        identifier=identifier,
        kind=kind,
        component_id=component_id,
        native_ref=native_ref,
        version=version,
        digest=digest,
        mode=mode,
        source=source,
        session_hint=session_hint or session_hint_from_env(),
        extra=extra or {},
    )
    target = path or default_lock_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = use.to_json()
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        use.extra = {}
        line = use.to_json()
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return use


def read_all(path: Path | None = None) -> list[CapabilityUse]:
    target = path or default_lock_path()
    if not target.is_file():
        return []
    uses: list[CapabilityUse] = []
    with target.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            parsed = CapabilityUse.from_json(line)
            if parsed is not None:
                uses.append(parsed)
    return uses


def _same_or_parent(candidate: str, root: str) -> bool:
    """True when ``candidate`` is ``root`` or lives under it."""
    try:
        Path(candidate).resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


def matching(
    *,
    harness: str | None,
    cwd: str | None,
    since: datetime | None,
    until: datetime | None = None,
    session_hint: str | None = None,
    path: Path | None = None,
) -> list[CapabilityUse]:
    """Uses that belong to a session: same harness, same tree, inside the window.

    A matching ``session_hint`` wins outright. Otherwise the harness must match
    (or be unknown on the use), the use's directory must be the session's
    directory or under it, and the timestamp must fall inside the window.
    """
    out: list[CapabilityUse] = []
    for use in read_all(path):
        if session_hint and use.session_hint and use.session_hint == session_hint:
            out.append(use)
            continue
        if harness and use.harness and use.harness != harness:
            continue
        if cwd and use.cwd and not _same_or_parent(use.cwd, cwd):
            continue
        ts = use.timestamp
        if since and ts < since:
            continue
        if until and ts > until:
            continue
        out.append(use)
    return out


def dedupe_latest(uses: Iterable[CapabilityUse]) -> list[CapabilityUse]:
    """One entry per resource, keeping the most recent use."""
    latest: dict[str, CapabilityUse] = {}
    for use in sorted(uses, key=lambda u: u.ts):
        key = use.identifier or f"{use.kind}:{use.component_id or use.native_ref}"
        latest[key] = use
    return list(latest.values())


def prune(
    *, retention_days: int = DEFAULT_RETENTION_DAYS, path: Path | None = None, now: datetime | None = None
) -> int:
    """Drop uses older than the retention window. Returns how many were removed."""
    target = path or default_lock_path()
    uses = read_all(target)
    if not uses:
        return 0
    cutoff = (now or _now()) - timedelta(days=retention_days)
    kept = [u for u in uses if u.timestamp >= cutoff]
    removed = len(uses) - len(kept)
    if removed:
        tmp = target.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(u.to_json() + "\n" for u in kept), encoding="utf-8")
        os.replace(tmp, target)
    return removed


def to_payload(uses: Iterable[CapabilityUse], *, confidence: str) -> list[dict]:
    """Shape uses for the ingest payload's ``capabilities_used`` field."""
    return [
        {
            "identifier": u.identifier,
            "kind": u.kind,
            "component_id": u.component_id,
            "native_ref": u.native_ref,
            "version": u.version,
            "digest": u.digest,
            "mode": u.mode,
            "source": u.source,
            "used_at": u.ts,
            "confidence": "exact" if u.session_hint else confidence,
        }
        for u in uses
    ]
