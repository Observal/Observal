"""SAML 2.0 Service Provider helpers."""

from __future__ import annotations

import base64
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID

logger = logging.getLogger("observal.ee.saml")

_ENCRYPTION_PREFIX = "enc:aesgcm:"


def generate_sp_key_pair(
    common_name: str = "Observal SP",
    validity_days: int = 3650,
) -> tuple[str, str]:
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
    return private_key_pem, cert_pem


def encrypt_private_key(private_key_pem: str, password: str) -> str:
    if not password:
        return private_key_pem
    h = hashes.Hash(hashes.SHA256())
    h.update(password.encode())
    aes_key = h.finalize()
    aesgcm = AESGCM(aes_key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, private_key_pem.encode(), None)
    payload = nonce + ciphertext
    return _ENCRYPTION_PREFIX + base64.b64encode(payload).decode()


def decrypt_private_key(encrypted: str, password: str) -> str:
    if not encrypted.startswith(_ENCRYPTION_PREFIX):
        return encrypted
    if not password:
        return encrypted
    payload = base64.b64decode(encrypted[len(_ENCRYPTION_PREFIX) :])
    nonce = payload[:12]
    ciphertext = payload[12:]
    h = hashes.Hash(hashes.SHA256())
    h.update(password.encode())
    aes_key = h.finalize()
    aesgcm = AESGCM(aes_key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode()


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
    strict: bool = True,
) -> dict[str, Any]:
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
            "NameIDFormat": "urn:oasis:names:tc:SAML:2.0:nameid-format:emailAddress",
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
            "wantNameIdEncrypted": False,
            "wantAssertionsEncrypted": False,
            "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
            "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
        },
    }
    if idp_slo_url:
        settings_dict["idp"]["singleLogoutService"] = {
            "url": idp_slo_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }
    return settings_dict


def _strip_pem_headers(pem: str) -> str:
    lines = pem.strip().splitlines()
    return "".join(line.strip() for line in lines if not line.strip().startswith("-----"))


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
