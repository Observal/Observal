# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""SAML 2.0 Service Provider helpers."""

from __future__ import annotations

import base64
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.x509.oid import NameOID
from loguru import logger as optic
from lxml import etree

import services.dynamic_settings as ds
from schemas.sso_health import make_check

_ENCRYPTION_PREFIX = "enc:aesgcm:v2:"
_PBKDF2_ITERATIONS = 600_000
_PEM_ARMOR_RE = re.compile(r"-----[A-Z0-9 ]+-----")
_WHITESPACE_RE = re.compile(r"\s+")
_HTTP_TIMEOUT = 10.0
_SAML_NS = {"md": "urn:oasis:names:tc:SAML:2.0:metadata", "ds": "http://www.w3.org/2000/09/xmldsig#"}


def _safe_xml_parse(xml: str) -> etree._Element:
    """Parse SAML metadata XML with entity expansion and network access disabled."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(xml.encode() if isinstance(xml, str) else xml, parser=parser)


def generate_sp_key_pair(
    common_name: str = "Observal SP",
    validity_days: int = 3650,
) -> tuple[str, str]:
    optic.debug("saml.generate_sp_key_pair common_name={} validity_days={}", common_name, validity_days)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Observal"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(days=validity_days))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    optic.info("saml.generate_sp_key_pair issued cert subject={}", common_name)
    return private_key_pem, cert_pem


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode())


def encrypt_private_key(private_key_pem: str, password: str) -> str:
    if not password:
        optic.warning("saml.encrypt_private_key called with empty password — storing plaintext")
        return private_key_pem
    salt = os.urandom(16)
    aes_key = _derive_key(password, salt)
    aesgcm = AESGCM(aes_key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, private_key_pem.encode(), None)
    payload = salt + nonce + ciphertext
    return _ENCRYPTION_PREFIX + base64.b64encode(payload).decode()


def decrypt_private_key(encrypted: str, password: str) -> str:
    if encrypted.startswith(_ENCRYPTION_PREFIX):
        if not password:
            optic.warning("saml.decrypt_private_key called without password on encrypted key")
            return encrypted
        payload = base64.b64decode(encrypted[len(_ENCRYPTION_PREFIX) :])
        salt = payload[:16]
        nonce = payload[16:28]
        ciphertext = payload[28:]
        aes_key = _derive_key(password, salt)
        aesgcm = AESGCM(aes_key)
        return aesgcm.decrypt(nonce, ciphertext, None).decode()
    return encrypted


def build_saml_settings(
    *,
    idp_entity_id: str,
    idp_sso_url: str,
    idp_x509_cert: str,
    sp_entity_id: str,
    sp_acs_url: str,
    sp_private_key: str,
    sp_x509_cert: str,
    idp_slo_url: str = "",
    sp_slo_url: str = "",
    strict: bool = True,
) -> dict[str, Any]:
    optic.trace("saml.build_saml_settings idp={} sp={} acs={}", idp_entity_id, sp_entity_id, sp_acs_url)
    sp_cert_clean = _strip_pem_headers(sp_x509_cert)
    sp_key_clean = _strip_pem_headers(sp_private_key)
    idp_cert_clean = _strip_pem_headers(idp_x509_cert)

    settings_dict: dict[str, Any] = {
        "strict": strict,
        "debug": False,
        "sp": {
            "entityId": sp_entity_id,
            "assertionConsumerService": {
                "url": sp_acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "x509cert": sp_cert_clean,
            "privateKey": sp_key_clean,
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },
        "idp": {
            "entityId": idp_entity_id,
            "singleSignOnService": {
                "url": idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": idp_cert_clean,
        },
        "security": {
            "authnRequestsSigned": True,
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "wantResponsesSigned": True,
            "wantNameIdEncrypted": False,
            "wantAssertionsEncrypted": False,
            "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
            "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
            "requestedAuthnContext": False,
            "relaxDestinationValidation": False,
            "wantNameId": True,
        },
    }
    if sp_slo_url:
        settings_dict["sp"]["singleLogoutService"] = {
            "url": sp_slo_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }
    if idp_slo_url:
        settings_dict["idp"]["singleLogoutService"] = {
            "url": idp_slo_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }
    return settings_dict


def check_cert_expiry(cert_pem: str, label: str) -> dict[str, Any] | None:
    name = f"{label.lower()}_cert_expiry"
    pretty = f"{label} X.509 certificate expiry"
    if not cert_pem:
        optic.trace("saml.check_cert_expiry skip label={}: no cert", label)
        return None
    try:
        body = cert_pem.strip()
        if "BEGIN CERTIFICATE" not in body:
            body = f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----"
        cert = x509.load_pem_x509_certificate(body.encode())
    except Exception:
        optic.warning("saml.check_cert_expiry parse failed label={}", label)
        return make_check(
            name,
            pretty,
            "fail",
            f"{label} X.509 certificate is malformed or could not be parsed.",
            f"Re-import the {label} certificate.",
        )
    not_after = (
        cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=UTC)
    )
    now = datetime.now(UTC)
    optic.debug("saml.check_cert_expiry label={} not_after={}", label, not_after.isoformat())
    if not_after < now:
        return make_check(
            name,
            pretty,
            "fail",
            f"{label} X.509 certificate expired on {not_after.date().isoformat()}.",
            f"Rotate the {label} certificate immediately.",
        )
    if not_after < now + timedelta(days=7):
        return make_check(
            name,
            pretty,
            "fail",
            f"{label} X.509 certificate expires within 7 days (on {not_after.date().isoformat()}).",
            f"Rotate the {label} certificate before it expires.",
        )
    return make_check(name, pretty, "pass")


def check_sp_host_consistency(sp_acs_url: str, frontend_url: str) -> dict[str, Any]:
    name, label = "sp_host_consistency", "SP ACS host matches frontend"
    sp_host = urlparse(sp_acs_url or "").hostname
    fe_host = urlparse(frontend_url or "").hostname
    optic.trace("saml.check_sp_host_consistency sp={} fe={}", sp_host, fe_host)
    if sp_host and fe_host and sp_host != fe_host:
        optic.warning("saml.check_sp_host_consistency mismatch sp={} fe={}", sp_host, fe_host)
        return make_check(
            name,
            label,
            "fail",
            (
                f"SP ACS host ({sp_host}) does not match deployment.frontend_url host ({fe_host}) — "
                f"the IdP will send assertions to {sp_host} but this deployment is reachable as {fe_host}."
            ),
            "Either update the SP ACS URL or change deployment.frontend_url so they share the same host.",
        )
    return make_check(name, label, "pass")


async def _fetch_idp_metadata(metadata_url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(metadata_url)
            resp.raise_for_status()
            optic.debug("saml._fetch_idp_metadata ok url={} bytes={}", metadata_url, len(resp.text))
            return resp.text
    except Exception:
        optic.warning("saml._fetch_idp_metadata failed url={}", metadata_url)
        return None


def _extract_metadata_certs(xml: str) -> list[str] | None:
    try:
        root = _safe_xml_parse(xml)
    except etree.XMLSyntaxError:
        optic.warning("saml._extract_metadata_certs invalid XML")
        return None
    nodes = root.iterfind(".//ds:X509Certificate", _SAML_NS)
    return [n.text or "" for n in nodes if (n.text or "").strip()]


def _extract_metadata_nameid_formats(xml: str) -> list[str] | None:
    try:
        root = _safe_xml_parse(xml)
    except etree.XMLSyntaxError:
        return None
    nodes = root.iterfind(".//md:NameIDFormat", _SAML_NS)
    return [n.text or "" for n in nodes if (n.text or "").strip()]


async def check_idp_cert_against_metadata(configured_cert: str) -> dict[str, Any] | None:
    name, label = "idp_cert_matches_metadata", "IdP cert matches metadata"
    metadata_url = ds.get_sync("saml.idp_metadata_url", "")
    if not metadata_url:
        return None
    xml = await _fetch_idp_metadata(metadata_url)
    if xml is None:
        return make_check(
            name,
            label,
            "fail",
            "IdP metadata URL is configured but unreachable.",
            "Verify saml.idp_metadata_url is correct and reachable from this server.",
        )
    certs = _extract_metadata_certs(xml)
    if certs is None:
        return make_check(
            name,
            label,
            "fail",
            "IdP metadata is not valid XML.",
            "Confirm the metadata URL returns a SAML EntityDescriptor document.",
        )
    if not certs:
        return make_check(
            name,
            label,
            "fail",
            "IdP metadata contains no X509Certificate elements.",
            "Confirm the metadata URL returns a valid SAML EntityDescriptor.",
        )
    configured = _strip_pem_headers(configured_cert)
    if configured and configured not in [_strip_pem_headers(c) for c in certs]:
        optic.warning("saml.check_idp_cert_against_metadata configured cert not in metadata signing certs")
        return make_check(
            name,
            label,
            "fail",
            "The configured IdP X.509 certificate does not match any signing certificate in the IdP metadata.",
            "Re-import the IdP certificate from the current metadata document.",
        )
    return make_check(name, label, "pass")


def check_sp_cert_key_match(sp_cert_pem: str, sp_private_key_pem: str) -> dict[str, Any] | None:
    name, label = "sp_cert_key_match", "SP cert/key form a valid pair"
    if not sp_cert_pem or not sp_private_key_pem:
        return None
    try:
        cert_body = sp_cert_pem.strip()
        if "BEGIN CERTIFICATE" not in cert_body:
            cert_body = f"-----BEGIN CERTIFICATE-----\n{cert_body}\n-----END CERTIFICATE-----"
        cert = x509.load_pem_x509_certificate(cert_body.encode())
        key = serialization.load_pem_private_key(sp_private_key_pem.encode(), password=None)
    except Exception:
        optic.warning("saml.check_sp_cert_key_match parse failed")
        return make_check(
            name,
            label,
            "fail",
            "SP certificate or private key could not be parsed.",
            "Regenerate the SP key pair from the admin SAML page.",
        )
    try:
        cert_pub = cert.public_key().public_numbers()  # type: ignore[attr-defined]
        key_pub = key.public_key().public_numbers()  # type: ignore[attr-defined]
    except AttributeError:
        optic.trace("saml.check_sp_cert_key_match non-RSA key, skipping")
        return None
    if cert_pub != key_pub:
        optic.warning("saml.check_sp_cert_key_match mismatch — cert and key do not pair")
        return make_check(
            name,
            label,
            "fail",
            "SP certificate and private key do not match — assertions will be signed with the wrong key.",
            "Regenerate the SP key pair from the admin SAML page so the cert and key are paired.",
        )
    return make_check(name, label, "pass")


async def check_idp_sso_url_reachable(idp_sso_url: str) -> dict[str, Any] | None:
    name, label = "idp_sso_reachable", "IdP SSO URL reachable"
    if not idp_sso_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
            resp = await client.get(idp_sso_url)
    except Exception:
        optic.warning("saml.check_idp_sso_url_reachable network error url={}", idp_sso_url)
        return make_check(
            name,
            label,
            "fail",
            "IdP SSO URL is unreachable from this server.",
            "Verify the URL is correct and reachable (DNS, firewall, TLS).",
        )
    optic.debug("saml.check_idp_sso_url_reachable url={} status={}", idp_sso_url, resp.status_code)
    if resp.status_code >= 500:
        return make_check(
            name,
            label,
            "fail",
            f"IdP SSO URL returned HTTP {resp.status_code}.",
            "Check the identity provider's status — its SSO endpoint is erroring.",
        )
    return make_check(name, label, "pass")


async def check_nameid_format(configured_format: str = "emailAddress") -> dict[str, Any] | None:
    name, label = "nameid_format", "IdP advertises emailAddress NameIDFormat"
    metadata_url = ds.get_sync("saml.idp_metadata_url", "")
    if not metadata_url:
        return None
    xml = await _fetch_idp_metadata(metadata_url)
    if xml is None:
        return None
    formats = _extract_metadata_nameid_formats(xml)
    if not formats:
        return None
    joined = " ".join(formats).lower()
    if configured_format.lower() not in joined:
        optic.warning("saml.check_nameid_format mismatch want={} got={}", configured_format, formats)
        return make_check(
            name,
            label,
            "fail",
            (
                f"IdP metadata does not advertise the '{configured_format}' NameIDFormat — "
                "Observal expects NameID to contain the user's email."
            ),
            f"Configure the IdP application to send NameID in '{configured_format}' format.",
        )
    return make_check(name, label, "pass")


def _strip_pem_headers(pem: str) -> str:
    """Return the bare base64 body of a PEM blob, robust to single-line space-separated input."""
    if not pem:
        return ""
    body = _PEM_ARMOR_RE.sub("", pem)
    return _WHITESPACE_RE.sub("", body)


def extract_name_id_and_attrs(auth) -> tuple[str, dict[str, list[str]]]:
    name_id = auth.get_nameid() or ""
    attributes = auth.get_attributes() or {}
    return name_id.strip().lower(), attributes


def get_display_name(attributes: dict[str, list[str]], fallback: str = "SSO User") -> str:
    for attr_name in [
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
        "displayName",
        "cn",
        "urn:oid:2.16.840.1.113730.3.1.241",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
        "givenName",
        "firstName",
    ]:
        values = attributes.get(attr_name, [])
        if values and values[0].strip():
            return values[0].strip()
    return fallback
