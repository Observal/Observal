# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the asymmetric key management service (services/crypto.py).

Covers:
- Key generation (creates valid EC P-256 key pair)
- Key persistence (loads existing key on restart)
- JWKS format output
- Token signing and verification round-trip (raw + PyJWT)
- Key rotation (old tokens still verify with old public key)
- Password-protected keys
"""

from __future__ import annotations

import json
import os

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.crypto import (
    KeyManager,
    _b64url,
    _b64url_decode,
    _kid_from_public_key,
    get_key_manager,
    init_key_manager,
)


@pytest.fixture()
def tmp_key_dir(tmp_path):
    """Provide a temporary directory for key storage."""
    d = tmp_path / "keys"
    d.mkdir()
    return str(d)


@pytest.fixture()
def km(tmp_key_dir):
    """Return an initialized KeyManager with a fresh key pair."""
    manager = KeyManager(key_dir=tmp_key_dir)
    manager.initialize()
    return manager


# ===================================================================
# Key generation
# ===================================================================


class TestKeyGeneration:
    def test_generates_ec_key_pair(self, km):
        priv = km.get_private_key()
        pub = km.get_public_key()
        assert isinstance(priv, ec.EllipticCurvePrivateKey)
        assert isinstance(pub, ec.EllipticCurvePublicKey)
        # Must be P-256
        assert priv.curve.name == "secp256r1"

    def test_kid_is_deterministic(self, km):
        kid1 = km.get_kid()
        kid2 = _kid_from_public_key(km.get_public_key())
        assert kid1 == kid2

    def test_kid_is_hex_string(self, km):
        kid = km.get_kid()
        assert len(kid) == 16
        int(kid, 16)  # should not raise

    def test_public_key_pem_format(self, km):
        pem = km.get_public_key_pem()
        assert pem.startswith("-----BEGIN PUBLIC KEY-----")
        assert pem.strip().endswith("-----END PUBLIC KEY-----")

    def test_signing_pem_created_on_disk(self, tmp_key_dir):
        manager = KeyManager(key_dir=tmp_key_dir)
        manager.initialize()
        assert os.path.exists(os.path.join(tmp_key_dir, "signing.pem"))

    def test_key_file_permissions(self, tmp_key_dir):
        manager = KeyManager(key_dir=tmp_key_dir)
        manager.initialize()
        pem_path = os.path.join(tmp_key_dir, "signing.pem")
        mode = oct(os.stat(pem_path).st_mode & 0o777)
        assert mode == "0o600"


# ===================================================================
# Key persistence
# ===================================================================


class TestKeyPersistence:
    def test_loads_existing_key_on_restart(self, tmp_key_dir):
        # First boot: generate
        km1 = KeyManager(key_dir=tmp_key_dir)
        km1.initialize()
        kid1 = km1.get_kid()
        pem1 = km1.get_public_key_pem()

        # Second boot: load
        km2 = KeyManager(key_dir=tmp_key_dir)
        km2.initialize()
        kid2 = km2.get_kid()
        pem2 = km2.get_public_key_pem()

        assert kid1 == kid2
        assert pem1 == pem2

    def test_password_protected_key(self, tmp_key_dir):
        password = "test-password-1234"
        km1 = KeyManager(key_dir=tmp_key_dir, key_password=password)
        km1.initialize()
        kid1 = km1.get_kid()

        # Reload with correct password
        km2 = KeyManager(key_dir=tmp_key_dir, key_password=password)
        km2.initialize()
        assert km2.get_kid() == kid1

    def test_wrong_password_fails(self, tmp_key_dir):
        km1 = KeyManager(key_dir=tmp_key_dir, key_password="correct")
        km1.initialize()

        km2 = KeyManager(key_dir=tmp_key_dir, key_password="wrong")
        with pytest.raises((ValueError, TypeError)):
            km2.initialize()


# ===================================================================
# JWKS format
# ===================================================================


class TestJWKS:
    def test_jwks_structure(self, km):
        jwks = km.get_jwks()
        assert "keys" in jwks
        assert len(jwks["keys"]) == 1

    def test_jwk_fields(self, km):
        jwk = km.get_jwks()["keys"][0]
        assert jwk["kty"] == "EC"
        assert jwk["crv"] == "P-256"
        assert jwk["use"] == "sig"
        assert jwk["alg"] == "ES256"
        assert jwk["kid"] == km.get_kid()
        assert "x" in jwk
        assert "y" in jwk

    def test_jwk_coordinates_decode(self, km):
        jwk = km.get_jwks()["keys"][0]
        x_bytes = _b64url_decode(jwk["x"])
        y_bytes = _b64url_decode(jwk["y"])
        # P-256 coordinates are 32 bytes each
        assert len(x_bytes) == 32
        assert len(y_bytes) == 32

    def test_jwks_includes_retired_keys_after_rotation(self, km):
        old_kid = km.get_kid()
        km.rotate_key()
        jwks = km.get_jwks()
        assert len(jwks["keys"]) == 2
        kids = {k["kid"] for k in jwks["keys"]}
        assert old_kid in kids
        assert km.get_kid() in kids


# ===================================================================
# Token signing and verification — raw (no PyJWT)
# ===================================================================


class TestTokenRoundTripRaw:
    """Test the raw JWS implementation (no PyJWT dependency)."""

    def test_sign_and_verify_raw(self, km):
        payload = {"sub": "user-123", "role": "admin"}
        token = km._sign_token_raw(payload)
        decoded = km._verify_token_raw(token)
        assert decoded["sub"] == "user-123"
        assert decoded["role"] == "admin"

    def test_raw_token_is_three_part_jws(self, km):
        token = km._sign_token_raw({"test": True})
        parts = token.split(".")
        assert len(parts) == 3

    def test_raw_token_header_contains_kid(self, km):
        token = km._sign_token_raw({"test": True})
        header_b64 = token.split(".")[0]
        header = json.loads(_b64url_decode(header_b64))
        assert header["alg"] == "ES256"
        assert header["typ"] == "JWT"
        assert header["kid"] == km.get_kid()

    def test_tampered_payload_fails_verification(self, km):
        token = km._sign_token_raw({"sub": "user-123"})
        parts = token.split(".")
        # Tamper with the payload
        fake_payload = _b64url(json.dumps({"sub": "admin"}).encode())
        tampered = f"{parts[0]}.{fake_payload}.{parts[2]}"
        with pytest.raises((ValueError, InvalidSignature)):
            km._verify_token_raw(tampered)

    def test_invalid_token_format(self, km):
        with pytest.raises(ValueError, match="Invalid JWT format"):
            km._verify_token_raw("not.a.valid.token.at.all")

    def test_unknown_kid_fails(self, km):
        token = km._sign_token_raw({"sub": "user-123"})
        parts = token.split(".")
        # Forge header with unknown kid
        header = json.loads(_b64url_decode(parts[0]))
        header["kid"] = "unknown-kid-1234"
        fake_header = _b64url(json.dumps(header, separators=(",", ":")).encode())
        forged = f"{fake_header}.{parts[1]}.{parts[2]}"
        with pytest.raises(ValueError, match="Unknown key id"):
            km._verify_token_raw(forged)


# ===================================================================
# Token signing and verification — via sign_token / verify_token
# ===================================================================


class TestTokenRoundTrip:
    """Test the public sign_token / verify_token API (uses PyJWT if available)."""

    def test_sign_and_verify(self, km):
        payload = {"sub": "user-456", "role": "reviewer"}
        token = km.sign_token(payload)
        decoded = km.verify_token(token)
        assert decoded["sub"] == "user-456"
        assert decoded["role"] == "reviewer"

    def test_roundtrip_with_nested_payload(self, km):
        payload = {"data": {"items": [1, 2, 3]}, "count": 3}
        token = km.sign_token(payload)
        decoded = km.verify_token(token)
        assert decoded["data"]["items"] == [1, 2, 3]


# ===================================================================
# Key rotation
# ===================================================================


class TestKeyRotation:
    def test_rotation_generates_new_kid(self, km):
        old_kid = km.get_kid()
        km.rotate_key()
        new_kid = km.get_kid()
        assert old_kid != new_kid

    def test_old_token_still_verifies_after_rotation(self, km):
        payload = {"sub": "user-rotate", "test": True}
        token_before = km._sign_token_raw(payload)

        km.rotate_key()

        # Old token should still verify (raw implementation checks retired keys)
        decoded = km._verify_token_raw(token_before)
        assert decoded["sub"] == "user-rotate"

    def test_new_token_verifies_after_rotation(self, km):
        km.rotate_key()
        payload = {"sub": "user-new"}
        token = km._sign_token_raw(payload)
        decoded = km._verify_token_raw(token)
        assert decoded["sub"] == "user-new"

    def test_retired_key_persisted_on_disk(self, tmp_key_dir):
        km = KeyManager(key_dir=tmp_key_dir)
        km.initialize()
        old_kid = km.get_kid()

        km.rotate_key()

        retired_path = os.path.join(tmp_key_dir, f"retired_{old_kid}.pem")
        assert os.path.exists(retired_path)

    def test_retired_keys_loaded_on_restart(self, tmp_key_dir):
        km1 = KeyManager(key_dir=tmp_key_dir)
        km1.initialize()
        token = km1._sign_token_raw({"sub": "persist-test"})

        km1.rotate_key()
        new_kid = km1.get_kid()

        # Restart
        km2 = KeyManager(key_dir=tmp_key_dir)
        km2.initialize()
        assert km2.get_kid() == new_kid

        # Old token should verify via retired keys
        decoded = km2._verify_token_raw(token)
        assert decoded["sub"] == "persist-test"

    def test_multiple_rotations(self, km):
        kids = [km.get_kid()]
        for _ in range(3):
            km.rotate_key()
            kids.append(km.get_kid())

        # All kids should be unique
        assert len(set(kids)) == 4

        # JWKS should contain all 4 keys (1 current + 3 retired)
        jwks = km.get_jwks()
        assert len(jwks["keys"]) == 4

    def test_find_public_key(self, km):
        old_kid = km.get_kid()
        km.rotate_key()
        new_kid = km.get_kid()

        # Both should be findable
        assert km.find_public_key(old_kid) is not None
        assert km.find_public_key(new_kid) is not None
        # Unknown should return None
        assert km.find_public_key("nonexistent") is None


# ===================================================================
# Module-level singleton
# ===================================================================


class TestSingleton:
    def test_init_and_get(self, tmp_key_dir):
        km = init_key_manager(key_dir=tmp_key_dir)
        assert get_key_manager() is km

    def test_get_before_init_raises(self, monkeypatch):
        import services.crypto as mod

        monkeypatch.setattr(mod, "_key_manager", None)
        with pytest.raises(RuntimeError, match="not initialized"):
            get_key_manager()


# ===================================================================
# Base64url helpers
# ===================================================================


class TestBase64Url:
    def test_roundtrip(self):
        data = b"hello world"
        encoded = _b64url(data)
        decoded = _b64url_decode(encoded)
        assert decoded == data

    def test_no_padding(self):
        encoded = _b64url(b"a")
        assert "=" not in encoded


# ===================================================================
# JWKS HTTP endpoint
# ===================================================================


class TestJWKSEndpoint:
    """Test the GET /api/v1/auth/.well-known/jwks.json route."""

    @pytest.fixture()
    def jwks_app(self, tmp_key_dir):
        """Build a minimal FastAPI app with just the JWKS route."""
        import services.crypto as crypto_mod

        init_key_manager(key_dir=tmp_key_dir)

        from api.routes.jwks import router

        app = FastAPI()
        app.include_router(router)
        yield app
        # Cleanup singleton so other tests are not affected
        crypto_mod._key_manager = None

    @pytest.fixture()
    async def jwks_client(self, jwks_app):
        transport = ASGITransport(app=jwks_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_jwks_endpoint_returns_200(self, jwks_client):
        resp = await jwks_client.get("/api/v1/auth/.well-known/jwks.json")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_jwks_endpoint_returns_valid_jwks(self, jwks_client):
        resp = await jwks_client.get("/api/v1/auth/.well-known/jwks.json")
        data = resp.json()
        assert "keys" in data
        assert len(data["keys"]) >= 1
        key = data["keys"][0]
        assert key["kty"] == "EC"
        assert key["crv"] == "P-256"
        assert key["alg"] == "ES256"
        assert "kid" in key

    @pytest.mark.asyncio
    async def test_jwks_endpoint_cache_header(self, jwks_client):
        resp = await jwks_client.get("/api/v1/auth/.well-known/jwks.json")
        assert "max-age" in resp.headers.get("cache-control", "")
