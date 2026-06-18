# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared OIDC health-probe helpers.

Each probe returns a check dict ``{name, label, status, message?, hint?}`` so
the admin validator and the public sso-health endpoint can assemble a full
diagnostic report instead of bailing on the first failure. Returning ``None``
means the check did not run (skip).
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger as optic

from schemas.sso_health import make_check

_HTTP_TIMEOUT = 10.0
_HEALTH_PROBE_TIMEOUT = 8.0


async def fetch_discovery(metadata_url: str) -> tuple[dict | None, str | None, dict[str, Any]]:
    """Return ``(metadata, server_date_header, discovery_check)``.

    ``server_date_header`` is the response ``Date`` header so the caller can run
    a clock-skew check without re-fetching.
    """
    name, label = "discovery_doc", "OIDC discovery document"
    optic.debug("oidc.fetch_discovery url={}", metadata_url)
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(metadata_url)
            resp.raise_for_status()
            metadata = resp.json()
            server_date = resp.headers.get("date")
    except httpx.TimeoutException:
        optic.warning("oidc.fetch_discovery timeout url={}", metadata_url)
        return (
            None,
            None,
            make_check(
                name,
                label,
                "fail",
                f"Timed out fetching OIDC metadata from {metadata_url}.",
                "The identity provider did not respond within 10 seconds.",
            ),
        )
    except httpx.HTTPStatusError as e:
        optic.warning("oidc.fetch_discovery http {} url={}", e.response.status_code, metadata_url)
        return (
            None,
            None,
            make_check(
                name,
                label,
                "fail",
                f"OIDC metadata endpoint returned HTTP {e.response.status_code}.",
                f"Check that {metadata_url} is correct and accessible from the server.",
            ),
        )
    except Exception:
        optic.exception("oidc.fetch_discovery unexpected failure url={}", metadata_url)
        return (
            None,
            None,
            make_check(
                name,
                label,
                "fail",
                "Failed to fetch OIDC metadata.",
                "Verify OAUTH_SERVER_METADATA_URL is a reachable URL.",
            ),
        )
    optic.info("oidc.fetch_discovery ok issuer={}", metadata.get("issuer"))
    return metadata, server_date, make_check(name, label, "pass")


async def probe_authorization_endpoint(
    authz_endpoint: str,
    client_id: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Hit the IdP auth endpoint with the real redirect_uri and client_id.

    Server-side validation has limits: we cannot read the IdP's hosted login
    page intent — we treat 3xx (without ``error=``) and 200 as accepted, and
    everything else as rejected.
    """
    name, label = "authorization_endpoint", "Authorization endpoint accepts our params"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
            resp = await client.get(
                authz_endpoint,
                params={
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "openid email profile groups",
                    "state": "observal_validate_probe",
                    "nonce": "observal_validate_nonce",
                },
            )
    except httpx.TimeoutException:
        optic.warning("oidc.probe_authorization_endpoint timeout endpoint={}", authz_endpoint)
        return make_check(
            name,
            label,
            "fail",
            "Timed out connecting to the authorization endpoint.",
            "The IdP did not respond. Check network connectivity.",
        )
    except Exception:
        optic.exception("oidc.probe_authorization_endpoint network error endpoint={}", authz_endpoint)
        return make_check(
            name,
            label,
            "fail",
            "Failed to reach the authorization endpoint.",
            "Check that the IdP is reachable from this server.",
        )
    optic.debug("oidc.probe_authorization_endpoint status={} endpoint={}", resp.status_code, authz_endpoint)
    if resp.status_code in (301, 302, 303, 307, 308):
        if "error=" in resp.headers.get("location", ""):
            return make_check(
                name,
                label,
                "fail",
                "IdP returned an authorization error redirect.",
                f"Ensure '{redirect_uri}' is registered as a redirect URI in your IdP application.",
            )
        return make_check(name, label, "pass")
    if resp.status_code == 200:
        return make_check(name, label, "pass")
    body = resp.text.lower()
    msg = f"IdP authorization endpoint returned HTTP {resp.status_code}."
    hint = f"Ensure '{redirect_uri}' is registered and the client is enabled."
    if "redirect_uri" in body or "redirect uri" in body:
        msg = "IdP rejected the redirect_uri — it is not registered in the application."
    elif "invalid_client" in body:
        msg = "IdP does not recognize this client_id."
    elif "unauthorized_client" in body:
        msg = "Client is not authorized for this grant type."
    return make_check(name, label, "fail", msg, hint)


async def probe_client_secret(
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict[str, Any] | None:
    """Validate ``client_secret`` by exchanging a deliberately-invalid code.

    The IdP returns ``invalid_grant`` when the secret is good and the code is
    bad; ``invalid_client`` / 401 when the secret itself is wrong.
    """
    name, label = "client_secret", "Token endpoint accepts client_secret"
    if not client_secret:
        return None
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": "observal_validate_invalid_code",
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
    except Exception:
        optic.warning("oidc.probe_client_secret network error endpoint={}", token_endpoint)
        return None
    err = ""
    try:
        err = (resp.json().get("error") or "").lower()
    except Exception:
        pass
    optic.debug("oidc.probe_client_secret status={} error={}", resp.status_code, err)
    if resp.status_code == 401 or err in ("invalid_client", "unauthorized_client"):
        return make_check(
            name,
            label,
            "fail",
            "IdP rejected our client credentials — the client_secret is wrong or the client is disabled.",
            "Check that OAUTH_CLIENT_SECRET matches the secret in your IdP application.",
        )
    return make_check(name, label, "pass")


async def probe_jwks(metadata: dict) -> dict[str, Any]:
    name, label = "jwks_reachable", "JWKS signing keys"
    jwks_uri = metadata.get("jwks_uri")
    if not jwks_uri:
        return make_check(
            name,
            label,
            "fail",
            "Discovery document does not declare jwks_uri — ID token signatures cannot be verified.",
            "Configure the jwks_uri claim in the IdP's discovery document.",
        )
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(jwks_uri)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        optic.warning("oidc.probe_jwks unreachable url={}", jwks_uri)
        return make_check(
            name,
            label,
            "fail",
            "JWKS endpoint is unreachable or returned invalid JSON.",
            "Verify the IdP's JWKS endpoint is publicly reachable from this server.",
        )
    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(keys, list) or not keys:
        return make_check(
            name,
            label,
            "fail",
            "JWKS endpoint did not return any signing keys.",
            "Check that the IdP has at least one active signing key.",
        )
    optic.debug("oidc.probe_jwks ok keys={}", len(keys))
    return make_check(name, label, "pass")


def check_issuer_consistency(metadata: dict, metadata_url: str) -> dict[str, Any] | None:
    name, label = "issuer_host_matches", "Issuer host matches discovery URL"
    issuer = (metadata.get("issuer") or "").rstrip("/")
    if not issuer:
        return None
    issuer_host = urlparse(issuer).hostname
    metadata_host = urlparse(metadata_url).hostname
    if issuer_host and metadata_host and issuer_host != metadata_host:
        optic.warning("oidc.check_issuer_consistency mismatch issuer={} discovery={}", issuer_host, metadata_host)
        return make_check(
            name,
            label,
            "fail",
            f"Discovery `issuer` host ({issuer_host}) does not match the metadata URL host ({metadata_host}).",
            "OAUTH_SERVER_METADATA_URL likely points at the wrong tenant or environment.",
        )
    return make_check(name, label, "pass")


def check_token_endpoint_auth_methods(metadata: dict) -> dict[str, Any] | None:
    name, label = "token_auth_method_supported", "Token endpoint auth method"
    methods = [m.lower() for m in (metadata.get("token_endpoint_auth_methods_supported") or [])]
    if not methods:
        return None
    supported = {"client_secret_basic", "client_secret_post"}
    if not (supported & set(methods)):
        optic.warning("oidc.check_token_endpoint_auth_methods unsupported={}", methods)
        return make_check(
            name,
            label,
            "fail",
            f"IdP only advertises {methods} — Observal needs client_secret_basic or client_secret_post.",
            "Enable client_secret_basic or client_secret_post for this application in the IdP.",
        )
    return make_check(name, label, "pass")


def check_clock_skew(server_date_header: str | None) -> dict[str, Any] | None:
    name, label = "clock_skew", "Clock skew with IdP"
    if not server_date_header:
        return None
    try:
        idp_time = parsedate_to_datetime(server_date_header)
        if idp_time.tzinfo is None:
            idp_time = idp_time.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None
    skew = abs((datetime.now(UTC) - idp_time).total_seconds())
    optic.debug("oidc.check_clock_skew seconds={}", int(skew))
    if skew > 300:
        return make_check(
            name,
            label,
            "fail",
            f"Clock differs from the IdP by {int(skew)}s (>5min) — token nonce/exp checks will fail.",
            "Sync this server's clock with NTP.",
        )
    return make_check(name, label, "pass")


def check_email_scope(metadata: dict) -> dict[str, Any]:
    name, label = "email_scope", "Email scope/claim"
    scopes = [s.lower() for s in (metadata.get("scopes_supported") or [])]
    claims = [c.lower() for c in (metadata.get("claims_supported") or [])]
    if scopes and "email" not in scopes and "email" not in claims:
        return make_check(
            name,
            label,
            "fail",
            "The IdP does not advertise an 'email' scope or claim — Observal cannot create accounts without it.",
            "Enable the 'email' scope/claim for this application in your IdP.",
        )
    return make_check(name, label, "pass")


async def run_oidc_checks(
    metadata_url: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> tuple[list[dict[str, Any]], dict | None]:
    """Run every OIDC check and return ``(checks, metadata)``.

    Dependent checks short-circuit only when the data they need is unavailable —
    every other check runs so the operator sees every issue at once.
    """
    optic.info("oidc.run_oidc_checks start metadata_url={}", metadata_url)
    checks: list[dict[str, Any]] = []
    metadata, server_date, discovery_check = await fetch_discovery(metadata_url)
    checks.append(discovery_check)
    if metadata is None:
        return checks, None

    authz_endpoint = metadata.get("authorization_endpoint")
    token_endpoint = metadata.get("token_endpoint")
    if authz_endpoint:
        checks.append(await probe_authorization_endpoint(authz_endpoint, client_id, redirect_uri))
    else:
        checks.append(
            make_check(
                "authorization_endpoint",
                "Authorization endpoint accepts our params",
                "fail",
                "Discovery document is missing authorization_endpoint.",
                "Verify the IdP configuration exposes a valid discovery document.",
            )
        )

    if token_endpoint:
        secret_check = await probe_client_secret(token_endpoint, client_id, client_secret, redirect_uri)
        if secret_check is not None:
            checks.append(secret_check)
    else:
        checks.append(
            make_check(
                "client_secret",
                "Token endpoint accepts client_secret",
                "fail",
                "Discovery document is missing token_endpoint.",
                "Verify the IdP configuration exposes a valid discovery document.",
            )
        )

    checks.append(check_email_scope(metadata))
    checks.append(await probe_jwks(metadata))
    for opt in (
        check_issuer_consistency(metadata, metadata_url),
        check_token_endpoint_auth_methods(metadata),
        check_clock_skew(server_date),
    ):
        if opt is not None:
            checks.append(opt)
    optic.info("oidc.run_oidc_checks done count={}", len(checks))
    return checks, metadata
