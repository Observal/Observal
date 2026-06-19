# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Per-step SSO login diagnostics, backed by Redis.

Two callers:

* **Real-login error capture** — the OIDC callback / SAML ACS handler builds a
  per-step check list in memory and *only* persists it on failure. The user is
  redirected to ``/login?sso_error=<corr_id>`` and the frontend fetches the
  diagnostics via a short-lived public endpoint. Happy-path logins cost nothing.

* **End-to-end test sessions** — the admin "End to End Test" button creates a
  session up front, polls it as the user clicks through the real IdP, and
  renders the same ``ChecksList`` UI. Sessions are always persisted because the
  poller needs them.

The schema stored in Redis is intentionally small and sanitized — no raw
assertions, no tokens, no PII beyond the actor email that the IdP returned
(which the operator needs to debug attribute-mapping issues).
"""

from __future__ import annotations

import html
import json
import re
import secrets
import time
from typing import Any, Literal

from loguru import logger as optic
from redis.exceptions import RedisError

from schemas.sso_health import all_pass
from services.redis import get_redis

# Session ids are URL-safe base64 (token_urlsafe) -- A-Z, a-z, 0-9, _, -.
# Anything else cannot be a legitimate id and must not flow into URLs/HTML.
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_\-]+")


def is_safe_session_id(value: str | None, max_len: int = 64) -> bool:
    """Constant-time-ish predicate for a legitimate session id.

    Used at every boundary where a value derived from external input might be
    used as a session id (URL state, RelayState, query param). Pairs with
    ``html.escape`` and ``urllib.parse.quote`` downstream as defence-in-depth.
    """
    return bool(value) and len(value) <= max_len and bool(_SAFE_ID_RE.fullmatch(value))


SessionMode = Literal["real", "e2e"]
SessionProvider = Literal["oidc", "saml"]

_SESSION_TTL_SECONDS = 600  # 10 minutes — long enough for an interactive login
_REDIS_PREFIX = "sso_diag:"

# Sentinel used in OIDC `state` and SAML `RelayState` to mark an e2e test
# round-trip. Exported so the OIDC callback (core) and SAML ACS (ee) can both
# detect it without duplicating the literal.
E2E_SENTINEL_PREFIX = "__e2e:"


def _key(session_id: str) -> str:
    return f"{_REDIS_PREFIX}{session_id}"


def new_session_id() -> str:
    """Opaque, URL-safe identifier. 22 chars ≈ 132 bits of entropy."""
    return secrets.token_urlsafe(16)


def _empty_session(session_id: str, provider: SessionProvider, mode: SessionMode) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "provider": provider,
        "mode": mode,
        "checks": [],
        "started_at": time.time(),
        "finished_at": None,
        "ok": None,
        "actor_email": None,
        "summary": None,
    }


async def create_session(provider: SessionProvider, mode: SessionMode) -> tuple[str, dict[str, Any]]:
    """Create a new diagnostics session. Returns (session_id, session_dict).

    The session is persisted to Redis with TTL even if no checks have run yet,
    so the frontend poller gets a 404 only if Redis is unreachable.
    """
    session_id = new_session_id()
    session = _empty_session(session_id, provider, mode)
    try:
        redis = get_redis()
        await redis.setex(_key(session_id), _SESSION_TTL_SECONDS, json.dumps(session))
    except RedisError as e:
        optic.warning("sso_diagnostics.create_session redis unavailable: {}", e)
        # Fail closed: the caller decides whether to proceed without persistence.
        raise
    optic.info("sso_diagnostics.create_session id={} provider={} mode={}", session_id, provider, mode)
    return session_id, session


async def _save(session: dict[str, Any]) -> None:
    try:
        redis = get_redis()
        await redis.setex(_key(session["session_id"]), _SESSION_TTL_SECONDS, json.dumps(session))
    except RedisError as e:
        optic.warning("sso_diagnostics._save redis unavailable: {}", e)


async def save_session(session: dict[str, Any]) -> None:
    """Persist a session dict in full. Used by callers that need to add
    out-of-band fields (e.g. OIDC state/nonce on /start) and don't want to
    pierce the encapsulation of ``_save``."""
    await _save(session)


async def get_session(session_id: str) -> dict[str, Any] | None:
    try:
        redis = get_redis()
        raw = await redis.get(_key(session_id))
    except RedisError as e:
        optic.warning("sso_diagnostics.get_session redis unavailable: {}", e)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        optic.error("sso_diagnostics.get_session corrupt entry id={}", session_id)
        return None


async def append_check(session_id: str, check: dict[str, Any]) -> None:
    """Append a single check and re-save. Idempotent on the storage side."""
    session = await get_session(session_id)
    if session is None:
        optic.warning("sso_diagnostics.append_check missing session id={}", session_id)
        return
    session["checks"].append(check)
    await _save(session)


async def record_actor(session_id: str, email: str | None) -> None:
    """Stash the actor email so the polling UI can show 'logged in as X'."""
    if not email:
        return
    session = await get_session(session_id)
    if session is None:
        return
    session["actor_email"] = email
    await _save(session)


async def finalize(
    session_id: str,
    checks: list[dict[str, Any]] | None = None,
    summary: str | None = None,
    actor_email: str | None = None,
) -> None:
    """Mark a session as finished. Pass ``checks`` to atomically replace.

    Used by the real-login error path: build the list in memory during the
    flow, call ``finalize`` once at the end with the whole list. Avoids a
    Redis round-trip per check on a fast happy path.
    """
    session = await get_session(session_id)
    if session is None:
        # We may be persisting checks for the first time (real-login error path).
        # Reconstruct an empty session so the saved record is still well-formed.
        session = _empty_session(session_id, "oidc", "real")
    if checks is not None:
        session["checks"] = checks
    if actor_email is not None:
        session["actor_email"] = actor_email
    if summary is not None:
        session["summary"] = summary
    session["ok"] = all_pass(session["checks"])
    session["finished_at"] = time.time()
    await _save(session)
    optic.info(
        "sso_diagnostics.finalize id={} ok={} checks={}",
        session_id,
        session["ok"],
        len(session["checks"]),
    )


def public_view(session: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a session for public exposure (no auth required)."""
    return {
        "session_id": session.get("session_id"),
        "provider": session.get("provider"),
        "mode": session.get("mode"),
        "ok": session.get("ok"),
        "checks": session.get("checks", []),
        "actor_email": session.get("actor_email"),
        "summary": session.get("summary"),
        "started_at": session.get("started_at"),
        "finished_at": session.get("finished_at"),
    }


# ── Observal-themed result page ───────────────────────────────────────────
#
# Rendered in the tab the admin used to authenticate at the IdP. The admin SSO
# page is the source of truth (it polls for the full report), so this page
# just confirms the round-trip finished and surfaces the headline result so
# the admin doesn't have to switch tabs to know whether to celebrate or dig.

_RESULT_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Observal · SSO end-to-end test</title>
  <style>
    :root {{
      --bg: #0b0b10;
      --surface: #14141c;
      --surface-2: #1a1a23;
      --border: #2a2a35;
      --text: #e6e6ec;
      --muted: #8a8a96;
      --accent: #8b7eff;
      --pass: #10b981;
      --fail: #ef4444;
      --skip: #6b7280;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--text); }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
            min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 32px 20px; }}
    .card {{
      width: 100%; max-width: 560px; background: var(--surface);
      border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
      box-shadow: 0 24px 48px -12px rgba(0,0,0,0.6);
    }}
    .header {{ padding: 28px 32px 20px; border-bottom: 1px solid var(--border); }}
    .brand {{ color: var(--muted); font-size: 11px;
              letter-spacing: 0.12em; text-transform: uppercase; font-weight: 500; }}
    h1 {{ font-size: 22px; margin: 12px 0 6px; font-weight: 600; letter-spacing: -0.01em; }}
    .subtitle {{ color: var(--muted); font-size: 13px; line-height: 1.5; margin: 0; }}
    .status-pill {{ display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px;
                     border-radius: 999px; font-size: 12px; font-weight: 500; margin-top: 14px;
                     background: var(--surface-2); border: 1px solid var(--border); }}
    .status-pill.pass {{ color: var(--pass); border-color: rgba(16,185,129,0.3); }}
    .status-pill.fail {{ color: var(--fail); border-color: rgba(239,68,68,0.3); }}
    .status-pill .ring {{ width: 8px; height: 8px; border-radius: 50%; }}
    .status-pill.pass .ring {{ background: var(--pass); box-shadow: 0 0 8px var(--pass); }}
    .status-pill.fail .ring {{ background: var(--fail); box-shadow: 0 0 8px var(--fail); }}
    .body {{ padding: 24px 32px; }}
    .meta {{ display: grid; grid-template-columns: max-content 1fr; gap: 6px 14px; font-size: 12px;
              color: var(--muted); }}
    .meta b {{ color: var(--text); font-weight: 500; word-break: break-all; }}
    .checks {{ margin: 22px 0 0; padding: 0; list-style: none; border-top: 1px solid var(--border); }}
    .checks li {{ display: flex; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--border);
                   font-size: 13px; }}
    .checks li:last-child {{ border-bottom: 0; }}
    .checks .icon {{ flex: 0 0 auto; width: 16px; height: 16px; margin-top: 1px; }}
    .checks .label {{ flex: 1 1 auto; color: var(--text); font-weight: 500; }}
    .checks .msg {{ color: var(--muted); margin-top: 2px; }}
    .footer {{ padding: 20px 32px; background: var(--surface-2); border-top: 1px solid var(--border);
                font-size: 12px; color: var(--muted); display: flex; align-items: center;
                justify-content: space-between; flex-wrap: wrap; gap: 10px; }}
    .btn {{ display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; font-size: 12px;
            font-weight: 500; background: var(--accent); color: white; border-radius: 8px;
            text-decoration: none; transition: filter 120ms ease; }}
    .btn:hover {{ filter: brightness(1.1); }}
    .btn.secondary {{ background: transparent; color: var(--muted); border: 1px solid var(--border); }}
    .btn.secondary:hover {{ color: var(--text); border-color: var(--accent); }}
    code {{ background: var(--surface-2); padding: 2px 6px; border-radius: 4px; font-size: 11px;
             color: var(--muted); font-family: ui-monospace, monospace; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div class="brand">Observal · SSO Diagnostics</div>
      <h1>{title}</h1>
      <p class="subtitle">{subtitle}</p>
      <div class="status-pill {pill_class}"><span class="ring"></span>{pill_label}</div>
    </div>
    <div class="body">
      <div class="meta">
        <span>Provider</span><b>{provider_label}</b>
        <span>Actor</span><b>{actor_label}</b>
        <span>Session</span><b><code>{session_id}</code></b>
      </div>
      {checks_html}
    </div>
    <div class="footer">
      <span>This window can be closed. Full report is in the admin SSO page.</span>
      <a class="btn" href="{admin_url}">Open admin SSO →</a>
    </div>
  </div>
</body>
</html>
"""


def _icon_svg(status: str) -> str:
    if status == "pass":
        color = "var(--pass)"
        path = '<path d="M5 10.5l3 3 7-7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
    elif status == "fail":
        color = "var(--fail)"
        path = (
            '<path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
        )
    else:
        color = "var(--skip)"
        path = '<path d="M5 10h10" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>'
    return f'<svg class="icon" viewBox="0 0 20 20" style="color:{color}">{path}</svg>'


def _escape(value: str) -> str:
    """HTML-escape a value for safe interpolation into element content or
    attribute-quoted positions. Uses stdlib ``html.escape`` (quote=True) so
    static analysis recognises it as a sanitizer."""
    return html.escape(str(value), quote=True)


def render_result_page(
    session_id: str,
    provider: str,
    ok: bool,
    checks: list[dict[str, Any]],
    actor_email: str | None,
    summary: str | None,
    admin_url: str,
) -> str:
    """Render the Observal-themed end-of-flow page shown in the IdP tab.

    All interpolations go through ``html.escape(quote=True)``. ``session_id``
    is additionally rejected at the boundary if it doesn't match the safe-id
    regex (defence-in-depth against tainted state values).
    """
    safe_session_id = session_id if is_safe_session_id(session_id) else "invalid"
    provider_label = "OIDC / OAuth 2.0" if provider == "oidc" else "SAML 2.0"
    if ok:
        title = "End-to-end test passed"
        subtitle = "Every step of the live login round-trip completed cleanly."
        pill_class, pill_label = "pass", "All checks passed"
    else:
        first_fail = next((c for c in checks if c.get("status") == "fail"), None)
        title = "End-to-end test finished with errors"
        subtitle = (
            f"Failed at: {first_fail.get('label')}." if first_fail else (summary or "See per-step details below.")
        )
        pill_class, pill_label = "fail", "Issues detected"

    items: list[str] = []
    for c in checks:
        status = c.get("status", "skip")
        label = _escape(c.get("label", c.get("name", "(check)")))
        msg = c.get("message")
        items.append(
            f'<li>{_icon_svg(status)}<div><div class="label">{label}</div>'
            + (f'<div class="msg">{_escape(msg)}</div>' if msg else "")
            + "</div></li>"
        )
    checks_html = (
        f'<ul class="checks">{"".join(items)}</ul>'
        if items
        else '<p class="subtitle" style="margin-top:18px">No checks recorded.</p>'
    )

    return _RESULT_PAGE_TEMPLATE.format(
        title=_escape(title),
        subtitle=_escape(subtitle),
        pill_class=pill_class,
        pill_label=_escape(pill_label),
        provider_label=_escape(provider_label),
        actor_label=_escape(actor_email or "(not returned)"),
        session_id=_escape(safe_session_id),
        checks_html=checks_html,
        admin_url=_escape(admin_url),
    )


def render_error_page(title: str, message: str, admin_url: str) -> str:
    """Render the same themed shell for early/structural failures (no session)."""
    return _RESULT_PAGE_TEMPLATE.format(
        title=_escape(title),
        subtitle=_escape(message),
        pill_class="fail",
        pill_label="Could not run",
        provider_label="—",
        actor_label="—",
        session_id="—",
        checks_html="",
        admin_url=_escape(admin_url),
    )
