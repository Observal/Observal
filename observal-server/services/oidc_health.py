# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared OIDC health-probe helpers.

Each probe returns a check dict ``{name, label, status, message?, hint?}`` so
the admin validator and the public sso-health endpoint can assemble a full
diagnostic report instead of bailing on the first failure. Returning ``None``
means the check did not run (skip).

All helpers take an already-built ``httpx.AsyncClient`` so we avoid
re-instantiating one (and its TLS context) per check.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger as optic

from schemas.sso_health import make_check

_HTTP_TIMEOUT = 10.0
_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB cap on any single response body
_CLOCK_SKEW_THRESHOLD = 120  # seconds — OIDC nonce/iat tolerance is typically 60-120s
# Observal sends the client secret via HTTP Basic (authlib default). If the
# IdP does not advertise this method, login fails at the token exchange.
_OBSERVAL_TOKEN_AUTH_METHOD = "client_secret_basic"


async def _bounded_get(client: httpx.AsyncClient, url: str) -> tuple[httpx.Response, bytes]:
    """GET with a hard ceiling on body size (defends against huge responses)."""
    async with client.stream("GET", url) as resp:
        resp.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > _MAX_BODY_BYTES:
                raise httpx.ReadError(f"Response exceeded {_MAX_BODY_BYTES} bytes")
            chunks.append(chunk)
        return resp, b"".join(chunks)


async def fetch_discovery(
    client: httpx.AsyncClient,
    metadata_url: str,
) -> tuple[dict | None, str | None, dict[str, Any]]:
    """Return ``(metadata, server_date_header, discovery_check)``.

    ``server_date_header`` is the response ``Date`` header so the caller can
    run a clock-skew check without re-fetching.
    """
    name, label = "discovery_doc", "OIDC discovery document"
    optic.debug("oidc.fetch_discovery url={}", metadata_url)
    try:
        resp, body = await _bounded_get(client, metadata_url)
        metadata = json.loads(body)
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
                "Verify oauth.server_metadata_url is a reachable URL.",
            ),
        )
    if not isinstance(metadata, dict):
        optic.warning("oidc.fetch_discovery non-object response type={}", type(metadata).__name__)
        return (
            None,
            server_date,
            make_check(
                name,
                label,
                "fail",
                "OIDC metadata endpoint did not return a JSON object.",
                "The IdP returned an unexpected payload — confirm the URL points at the discovery document.",
            ),
        )
    optic.info("oidc.fetch_discovery ok issuer={}", metadata.get("issuer"))
    return metadata, server_date, make_check(name, label, "pass")


async def probe_authorization_endpoint(
    client: httpx.AsyncClient,
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
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile groups",
        "state": "observal_validate_probe",
        "nonce": "observal_validate_nonce",
    }
    try:
        async with client.stream("GET", authz_endpoint, params=params) as resp:
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > _MAX_BODY_BYTES:
                    break
                chunks.append(chunk)
            body = b"".join(chunks)
            status_code = resp.status_code
            location = resp.headers.get("location", "")
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
    optic.debug("oidc.probe_authorization_endpoint status={} endpoint={}", status_code, authz_endpoint)
    if status_code in (301, 302, 303, 307, 308):
        if "error=" in location:
            return make_check(
                name,
                label,
                "fail",
                "IdP returned an authorization error redirect.",
                f"Ensure '{redirect_uri}' is registered as a redirect URI in your IdP application.",
            )
        return make_check(name, label, "pass")
    if status_code == 200:
        return make_check(name, label, "pass")
    text = body.decode("utf-8", errors="ignore").lower()
    msg = f"IdP authorization endpoint returned HTTP {status_code}."
    hint = f"Ensure '{redirect_uri}' is registered and the client is enabled."
    if "redirect_uri" in text or "redirect uri" in text:
        msg = "IdP rejected the redirect_uri — it is not registered in the application."
    elif "invalid_client" in text:
        msg = "IdP does not recognize this client_id."
    elif "unauthorized_client" in text:
        msg = "Client is not authorized for this grant type."
    return make_check(name, label, "fail", msg, hint)


async def probe_client_secret(
    client: httpx.AsyncClient,
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
            "Check that oauth.client_secret matches the secret in your IdP application.",
        )
    return make_check(name, label, "pass")


async def probe_jwks(client: httpx.AsyncClient, metadata: dict) -> dict[str, Any]:
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
        _, body = await _bounded_get(client, jwks_uri)
        data = json.loads(body)
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
            "oauth.server_metadata_url likely points at the wrong tenant or environment.",
        )
    return make_check(name, label, "pass")


def check_token_endpoint_auth_methods(metadata: dict) -> dict[str, Any] | None:
    """Verify the IdP supports the auth method Observal *actually uses*.

    Observal sends the client secret via HTTP Basic. When the discovery
    document advertises an explicit list and Basic isn't in it, the token
    exchange will fail with ``invalid_client`` even though the secret is
    correct.
    """
    name, label = "token_auth_method_supported", "Token endpoint advertises client_secret_basic"
    methods = [m.lower() for m in (metadata.get("token_endpoint_auth_methods_supported") or [])]
    if not methods:
        # Spec default per RFC 8414 is client_secret_basic — nothing to validate.
        return None
    if _OBSERVAL_TOKEN_AUTH_METHOD not in methods:
        optic.warning("oidc.check_token_endpoint_auth_methods missing basic methods={}", methods)
        return make_check(
            name,
            label,
            "fail",
            f"IdP advertises {methods} but Observal uses '{_OBSERVAL_TOKEN_AUTH_METHOD}'.",
            f"Enable {_OBSERVAL_TOKEN_AUTH_METHOD} for this application in the IdP.",
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
    if skew > _CLOCK_SKEW_THRESHOLD:
        return make_check(
            name,
            label,
            "fail",
            f"Clock differs from the IdP by {int(skew)}s — token nonce/exp checks will fail.",
            "Sync this server's clock with NTP (target drift <60s).",
        )
    return make_check(name, label, "pass")


_SUPPORTED_ID_TOKEN_ALGS: frozenset[str] = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "ES256",
        "ES384",
        "ES512",
        "PS256",
        "PS384",
        "PS512",
        "EdDSA",
    }
)


def check_id_token_signing_alg(metadata: dict) -> dict[str, Any] | None:
    """Verify the IdP advertises at least one alg we can verify.

    If the IdP only supports ``none`` (unsigned) or an obscure alg like
    ``HS512``, every id_token verification will fail at the token endpoint.
    """
    name, label = "id_token_alg", "ID token signing algorithm supported"
    advertised = [a for a in (metadata.get("id_token_signing_alg_values_supported") or []) if isinstance(a, str)]
    if not advertised:
        return None
    if "none" in {a.lower() for a in advertised} and len(advertised) == 1:
        return make_check(
            name,
            label,
            "fail",
            "IdP only advertises 'none' for ID token signing -- Observal rejects unsigned tokens.",
            "Enable an asymmetric signing algorithm (RS256/ES256) at the IdP.",
        )
    overlap = set(advertised) & _SUPPORTED_ID_TOKEN_ALGS
    if not overlap:
        return make_check(
            name,
            label,
            "fail",
            f"IdP advertises {advertised} but Observal can verify {sorted(_SUPPORTED_ID_TOKEN_ALGS)}.",
            "Enable an asymmetric alg (RS256 recommended) at the IdP.",
        )
    return make_check(name, label, "pass")


def check_refresh_token_grant(metadata: dict) -> dict[str, Any] | None:
    """Surface a soft warning when the IdP doesn't advertise refresh_token grant.

    Without refresh_token support, sessions die when the access token expires
    and the user must re-login. The probe stays as 'skip' rather than 'fail'
    because the auth flow still works -- this is a UX warning.
    """
    name, label = "refresh_token_grant", "Refresh tokens supported"
    grants = [g.lower() for g in (metadata.get("grant_types_supported") or []) if isinstance(g, str)]
    if not grants:
        return None
    if "refresh_token" not in grants:
        return make_check(
            name,
            label,
            "skip",
            "IdP does not advertise the refresh_token grant. Sessions will end when the access token expires.",
            "Enable refresh tokens (or 'offline_access' scope) on the OIDC client.",
        )
    return make_check(name, label, "pass")


def check_end_session_endpoint(metadata: dict) -> dict[str, Any] | None:
    """Warn if the IdP doesn't expose end_session_endpoint (no SLO from SP)."""
    name, label = "end_session_endpoint", "Single Logout endpoint advertised"
    if metadata.get("end_session_endpoint"):
        return make_check(name, label, "pass")
    return make_check(
        name,
        label,
        "skip",
        "IdP discovery doc has no end_session_endpoint -- logging out at the SP will not log the user out at the IdP.",
        "Configure the IdP to expose RP-initiated logout if available.",
    )


def check_pkce_methods(metadata: dict) -> dict[str, Any] | None:
    """If the IdP advertises a PKCE method list, ensure S256 is there.

    Some IdPs require PKCE even for confidential clients. Observal does not
    currently send a code_challenge; this surfaces as an info-level skip when
    the IdP signals it expects PKCE.
    """
    name, label = "pkce_supported", "PKCE not required by IdP"
    methods = [m.lower() for m in (metadata.get("code_challenge_methods_supported") or []) if isinstance(m, str)]
    if not methods:
        return make_check(name, label, "pass")
    # IdP advertising PKCE methods doesn't mean it's required, but is worth surfacing.
    return make_check(
        name,
        label,
        "skip",
        f"IdP advertises PKCE methods {methods}. If the client is configured 'Require PKCE', mobile/SPA logins may fail.",
        "Either disable 'Require PKCE' on the OIDC client, or expect PKCE-related errors.",
    )


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

    Independent post-discovery checks run concurrently. A single
    ``AsyncClient`` is shared across all calls so we set up TLS once.
    """
    optic.info("oidc.run_oidc_checks start metadata_url={}", metadata_url)
    checks: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
        metadata, server_date, discovery_check = await fetch_discovery(client, metadata_url)
        checks.append(discovery_check)
        if metadata is None:
            return checks, None

        authz_endpoint = metadata.get("authorization_endpoint")
        token_endpoint = metadata.get("token_endpoint")

        async def _authz() -> dict[str, Any]:
            if not authz_endpoint:
                return make_check(
                    "authorization_endpoint",
                    "Authorization endpoint accepts our params",
                    "fail",
                    "Discovery document is missing authorization_endpoint.",
                    "Verify the IdP configuration exposes a valid discovery document.",
                )
            return await probe_authorization_endpoint(client, authz_endpoint, client_id, redirect_uri)

        async def _secret() -> dict[str, Any] | None:
            if not token_endpoint:
                return make_check(
                    "client_secret",
                    "Token endpoint accepts client_secret",
                    "fail",
                    "Discovery document is missing token_endpoint.",
                    "Verify the IdP configuration exposes a valid discovery document.",
                )
            return await probe_client_secret(client, token_endpoint, client_id, client_secret, redirect_uri)

        async def _jwks() -> dict[str, Any]:
            return await probe_jwks(client, metadata)

        authz_check, secret_check, jwks_check = await asyncio.gather(_authz(), _secret(), _jwks())
        checks.append(authz_check)
        if secret_check is not None:
            checks.append(secret_check)
        checks.append(jwks_check)

    checks.append(check_email_scope(metadata))
    for opt in (
        check_issuer_consistency(metadata, metadata_url),
        check_token_endpoint_auth_methods(metadata),
        check_id_token_signing_alg(metadata),
        check_refresh_token_grant(metadata),
        check_end_session_endpoint(metadata),
        check_pkce_methods(metadata),
        check_clock_skew(server_date),
    ):
        if opt is not None:
            checks.append(opt)
    optic.info("oidc.run_oidc_checks done count={}", len(checks))
    return checks, metadata
