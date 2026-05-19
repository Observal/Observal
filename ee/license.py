# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Enterprise license validation.

Validates OBSERVAL_LICENSE_KEY — a signed JWT containing:
    {
        "org_id": "...",
        "features": ["insights", "saml", "scim", ...],
        "exp": 1750000000
    }

Signed with Ed25519 by the Observal team. Verified offline using the
embedded public key. No phone-home required.

Usage:
    from ee.license import require_license, get_license_info, is_feature_licensed

    require_license("insights")  # raises RuntimeError if not licensed
    info = get_license_info()    # returns LicenseInfo or None
    ok = is_feature_licensed("saml")  # bool
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field

logger = logging.getLogger("observal.ee.license")

# Ed25519 public key — hardcoded, not secret.
# Only the private key (kept offline by the Observal team) can sign licenses.
_PUBLIC_KEY_B64 = "X5Ia46wxT2AxZ6nFlvFnT7ZE6vXoVI208Io3TDoX6N8="

# The license key set by the customer in their .env
_LICENSE_KEY = os.environ.get("OBSERVAL_LICENSE_KEY", "")


@dataclass
class LicenseInfo:
    org_id: str
    features: list[str] = field(default_factory=list)
    expires_at: int = 0
    plan: str = "enterprise"

    @property
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.is_expired


# Cached license info (validated once at import/startup)
_license_info: LicenseInfo | None = None
_validated: bool = False


def _validate_license() -> LicenseInfo | None:
    """Validate the license key and return info, or None if invalid."""
    global _license_info, _validated

    if _validated:
        return _license_info

    _validated = True

    if not _LICENSE_KEY:
        logger.info("No OBSERVAL_LICENSE_KEY set — enterprise features disabled")
        return None

    try:
        # License format: base64(json_payload).base64(signature)
        # For now, accept unsigned keys for development (payload only).
        # Production will require Ed25519 signature verification.
        parts = _LICENSE_KEY.split(".")

        if len(parts) != 2:
            logger.error("Invalid license key format — expected payload.signature")
            return None

        payload_b64, signature_b64 = parts[0], parts[1]

        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            pub_key_bytes = base64.urlsafe_b64decode(_PUBLIC_KEY_B64)
            pub_key = Ed25519PublicKey.from_public_bytes(pub_key_bytes)
            sig_bytes = base64.urlsafe_b64decode(signature_b64)
            payload_bytes = payload_b64.encode("utf-8")
            pub_key.verify(sig_bytes, payload_bytes)
        except Exception as e:
            logger.error("License signature verification failed: %s", e)
            return None

        # Decode payload
        # Add padding if needed
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))

        info = LicenseInfo(
            org_id=payload.get("org_id", "unknown"),
            features=payload.get("features", []),
            expires_at=payload.get("exp", 0),
            plan=payload.get("plan", "enterprise"),
        )

        if info.is_expired:
            logger.warning("License expired at %s", info.expires_at)
            return None

        _license_info = info
        logger.info(
            "License validated: org=%s features=%s plan=%s",
            info.org_id,
            info.features,
            info.plan,
        )
        return info

    except Exception as e:
        logger.error("Failed to validate license: %s", e)
        return None


def get_license_info() -> LicenseInfo | None:
    """Get validated license info, or None if unlicensed."""
    return _validate_license()


def is_feature_licensed(feature: str) -> bool:
    """Check if a specific feature is licensed."""
    info = get_license_info()
    if info is None:
        return False
    # "all" grants everything
    return "all" in info.features or feature in info.features


def require_license(feature: str) -> None:
    """Raise RuntimeError if feature is not licensed.

    Use as a gate at module import time or in service initialization.
    """
    if not is_feature_licensed(feature):
        raise RuntimeError(
            f"Feature '{feature}' requires a valid Observal Enterprise license. "
            f"Set OBSERVAL_LICENSE_KEY or visit https://observal.dev/enterprise"
        )


def licensed_features() -> list[str]:
    """Return list of licensed features (for /config endpoint)."""
    info = get_license_info()
    if info is None:
        return []
    return info.features
