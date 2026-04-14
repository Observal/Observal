"""Asymmetric key management for JWT signing and verification (ES256 / ECDSA P-256).

This module provides:
- Automatic key-pair generation on first server boot
- PEM-based key persistence with optional password protection
- JWKS endpoint data for standard token verification
- Key rotation with old-key retention for graceful transition
- ``sign_token`` / ``verify_token`` helpers for JWT auth
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    """Base64url-encode *without* padding (per RFC 7515)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Base64url-decode, re-adding padding as needed."""
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _kid_from_public_key(pub: ec.EllipticCurvePublicKey) -> str:
    """Derive a deterministic key-id (kid) from the public key bytes."""
    raw = pub.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(raw).hexdigest()[:16]


def _public_key_to_jwk(pub: ec.EllipticCurvePublicKey, kid: str) -> dict:
    """Convert an EC public key to a JWK dict (RFC 7517 / 7518)."""
    numbers = pub.public_numbers()
    # P-256 coordinates are 32 bytes each
    x_bytes = numbers.x.to_bytes(32, byteorder="big")
    y_bytes = numbers.y.to_bytes(32, byteorder="big")
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(x_bytes),
        "y": _b64url(y_bytes),
        "kid": kid,
        "use": "sig",
        "alg": "ES256",
    }


# ---------------------------------------------------------------------------
# KeyManager
# ---------------------------------------------------------------------------


class KeyManager:
    """Manages ES256 (ECDSA P-256) key pairs for JWT signing.

    On first run the manager generates a new key pair and persists it to
    *key_dir*.  On subsequent runs the existing key is loaded.  Key rotation
    is supported: the current signing key is stored as ``signing.pem`` while
    retired public keys are kept as ``retired_<kid>.pem`` so tokens signed
    with a previous key can still be verified during a transition window.
    """

    def __init__(
        self,
        key_dir: str = "~/.observal/keys",
        key_password: str | None = None,
    ) -> None:
        self._key_dir = Path(key_dir).expanduser()
        self._key_password = key_password.encode() if key_password else None

        self._private_key: ec.EllipticCurvePrivateKey | None = None
        self._public_key: ec.EllipticCurvePublicKey | None = None
        self._kid: str | None = None

        # Retired public keys: kid -> EllipticCurvePublicKey
        self._retired_keys: dict[str, ec.EllipticCurvePublicKey] = {}

    # -- lifecycle -----------------------------------------------------------

    def initialize(self) -> None:
        """Load or generate the signing key pair.  Call once at startup."""
        self._key_dir.mkdir(parents=True, exist_ok=True)
        # Restrict directory to owner-only
        os.chmod(self._key_dir, 0o700)

        signing_path = self._key_dir / "signing.pem"
        if signing_path.exists():
            self._load_private_key(signing_path)
            logger.info("Loaded existing signing key (kid=%s)", self._kid)
        else:
            self._generate_key_pair(signing_path)
            logger.info("Generated new signing key (kid=%s)", self._kid)

        self._load_retired_keys()

    # -- public API ----------------------------------------------------------

    def get_private_key(self) -> ec.EllipticCurvePrivateKey:
        """Return the current signing private key."""
        if self._private_key is None:
            raise RuntimeError("KeyManager has not been initialized")
        return self._private_key

    def get_public_key(self) -> ec.EllipticCurvePublicKey:
        """Return the current signing public key."""
        if self._public_key is None:
            raise RuntimeError("KeyManager has not been initialized")
        return self._public_key

    def get_kid(self) -> str:
        """Return the key-id of the current signing key."""
        if self._kid is None:
            raise RuntimeError("KeyManager has not been initialized")
        return self._kid

    def get_public_key_pem(self) -> str:
        """Return the PEM-encoded public key for distribution."""
        return (
            self.get_public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )

    def get_jwks(self) -> dict:
        """Return all public keys (current + retired) in JWKS format."""
        keys: list[dict] = []
        # Current key
        keys.append(_public_key_to_jwk(self.get_public_key(), self.get_kid()))
        # Retired keys
        for kid, pub in self._retired_keys.items():
            keys.append(_public_key_to_jwk(pub, kid))
        return {"keys": keys}

    def rotate_key(self) -> str:
        """Generate a new signing key, retiring the current one.

        Returns the *kid* of the newly generated key.
        """
        if self._public_key is not None and self._kid is not None:
            # Persist current public key as retired
            retired_path = self._key_dir / f"retired_{self._kid}.pem"
            retired_path.write_bytes(
                self._public_key.public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            self._retired_keys[self._kid] = self._public_key
            logger.info("Retired signing key kid=%s", self._kid)

        signing_path = self._key_dir / "signing.pem"
        self._generate_key_pair(signing_path)
        logger.info("Rotated to new signing key kid=%s", self._kid)
        return self.get_kid()

    def find_public_key(self, kid: str) -> ec.EllipticCurvePublicKey | None:
        """Look up a public key by its *kid* (current or retired)."""
        if kid == self._kid:
            return self._public_key
        return self._retired_keys.get(kid)

    # -- payload encryption/decryption ---------------------------------------

    def decrypt_payload(self, encrypted_blob: bytes) -> str:
        """Decrypt an ECIES-encrypted payload from the CLI buffer.

        Format: ephemeral_pubkey (65 bytes) || nonce (12 bytes) || ciphertext+tag
        """
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF

        # Parse components
        ephemeral_pub_bytes = encrypted_blob[:65]
        nonce = encrypted_blob[65:77]
        ciphertext_with_tag = encrypted_blob[77:]

        # Reconstruct ephemeral public key
        ephemeral_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ephemeral_pub_bytes)

        # ECDH shared secret using server's private key
        shared_secret = self.get_private_key().exchange(ec.ECDH(), ephemeral_pub)

        # Derive same AES key
        aes_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"observal-buffer-v1",
        ).derive(shared_secret)

        # Decrypt
        aesgcm = AESGCM(aes_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
        return plaintext.decode("utf-8")

    # -- token helpers -------------------------------------------------------

    def sign_token(self, payload: dict) -> str:
        """Sign a JWT-like payload with the current private key.

        Produces a compact JWS (header.payload.signature) using ES256.
        If ``PyJWT`` is installed this delegates to it; otherwise a
        minimal implementation using the ``cryptography`` library is used.
        """
        try:
            import jwt as pyjwt

            return pyjwt.encode(
                payload,
                self.get_private_key(),
                algorithm="ES256",
                headers={"kid": self.get_kid()},
            )
        except ImportError:
            pass

        return self._sign_token_raw(payload)

    def verify_token(self, token: str) -> dict:
        """Verify and decode a JWT signed by this server.

        Supports tokens signed with both the current and retired keys.
        """
        try:
            import jwt as pyjwt

            # Extract kid from unverified header
            header = pyjwt.get_unverified_header(token)
            kid = header.get("kid", self.get_kid())
            pub = self.find_public_key(kid)
            if pub is None:
                raise ValueError(f"Unknown key id: {kid}")
            return pyjwt.decode(token, pub, algorithms=["ES256"])
        except ImportError:
            pass

        return self._verify_token_raw(token)

    # -- internal ------------------------------------------------------------

    def _encryption_args(self) -> serialization.KeySerializationEncryption:
        if self._key_password:
            return serialization.BestAvailableEncryption(self._key_password)
        return serialization.NoEncryption()

    def _generate_key_pair(self, path: Path) -> None:
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            self._encryption_args(),
        )
        path.write_bytes(pem)
        os.chmod(path, 0o600)
        self._private_key = key
        self._public_key = key.public_key()
        self._kid = _kid_from_public_key(self._public_key)

    def _load_private_key(self, path: Path) -> None:
        pem_data = path.read_bytes()
        key = serialization.load_pem_private_key(pem_data, password=self._key_password)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise TypeError(f"Expected an EC private key, got {type(key).__name__}")
        self._private_key = key
        self._public_key = key.public_key()
        self._kid = _kid_from_public_key(self._public_key)

    def _load_retired_keys(self) -> None:
        for p in self._key_dir.glob("retired_*.pem"):
            try:
                pub = serialization.load_pem_public_key(p.read_bytes())
                if isinstance(pub, ec.EllipticCurvePublicKey):
                    kid = _kid_from_public_key(pub)
                    self._retired_keys[kid] = pub
                    logger.debug("Loaded retired key kid=%s from %s", kid, p.name)
            except Exception:
                logger.warning("Failed to load retired key %s", p, exc_info=True)

    # -- raw JWS (no PyJWT dependency) ---------------------------------------

    def _sign_token_raw(self, payload: dict) -> str:
        """Minimal JWS compact serialization using ``cryptography``."""
        header = {"alg": "ES256", "typ": "JWT", "kid": self.get_kid()}
        segments = [
            _b64url(json.dumps(header, separators=(",", ":")).encode()),
            _b64url(json.dumps(payload, separators=(",", ":")).encode()),
        ]
        signing_input = f"{segments[0]}.{segments[1]}".encode()

        # ECDSA signature in DER, convert to fixed-size (r || s) per RFC 7518
        der_sig = self.get_private_key().sign(
            signing_input,
            ec.ECDSA(hashes.SHA256()),
        )
        r, s = utils.decode_dss_signature(der_sig)
        sig_bytes = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        segments.append(_b64url(sig_bytes))
        return ".".join(segments)

    def _verify_token_raw(self, token: str) -> dict:
        """Minimal JWS verification using ``cryptography``."""
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT format")

        header = json.loads(_b64url_decode(parts[0]))
        kid = header.get("kid", self.get_kid())
        pub = self.find_public_key(kid)
        if pub is None:
            raise ValueError(f"Unknown key id: {kid}")

        signing_input = f"{parts[0]}.{parts[1]}".encode()
        sig_bytes = _b64url_decode(parts[2])

        if len(sig_bytes) != 64:
            raise ValueError("Invalid signature length")

        r = int.from_bytes(sig_bytes[:32], "big")
        s = int.from_bytes(sig_bytes[32:], "big")
        der_sig = utils.encode_dss_signature(r, s)

        pub.verify(der_sig, signing_input, ec.ECDSA(hashes.SHA256()))

        payload = json.loads(_b64url_decode(parts[1]))
        return payload


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_key_manager: KeyManager | None = None


def get_key_manager() -> KeyManager:
    """Return the global KeyManager instance (must be initialized first)."""
    if _key_manager is None:
        raise RuntimeError("KeyManager not initialized. Call init_key_manager() during app startup.")
    return _key_manager


def init_key_manager(
    key_dir: str = "~/.observal/keys",
    key_password: str | None = None,
) -> KeyManager:
    """Create, initialize, and register the global KeyManager singleton."""
    global _key_manager
    km = KeyManager(key_dir=key_dir, key_password=key_password)
    km.initialize()
    _key_manager = km
    return km


# Convenience wrappers ------------------------------------------------------


def sign_token(payload: dict) -> str:
    """Sign a JWT payload with the server's private key."""
    return get_key_manager().sign_token(payload)


def verify_token(token: str) -> dict:
    """Verify and decode a JWT using the server's public key."""
    return get_key_manager().verify_token(token)
