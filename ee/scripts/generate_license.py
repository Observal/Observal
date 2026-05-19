#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise
"""Generate a signed Observal Enterprise license key.

Usage:
    python3 generate_license.py --org acme-corp --features all --days 365

You will be prompted for the passphrase. The signing key is derived
deterministically from it — no key files, no secrets to manage.

Output:
    OBSERVAL_LICENSE_KEY=eyJ...

The customer pastes this single line into their .env. Nothing else needed.
"""

import argparse
import base64
import datetime
import getpass
import hashlib
import json
import time


def derive_private_key(passphrase: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    seed = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), b"observal-license-v1", 100_000)
    return Ed25519PrivateKey.from_private_bytes(seed[:32])


def main():
    parser = argparse.ArgumentParser(description="Generate an Observal license key")
    parser.add_argument("--org", required=True, help="Organisation ID (e.g. acme-corp)")
    parser.add_argument(
        "--features",
        nargs="+",
        default=["all"],
        help='Licensed features. Use "all" to grant everything (default: all)',
    )
    parser.add_argument("--days", type=int, default=365, help="Validity in days (default: 365)")
    parser.add_argument("--plan", default="enterprise", help="Plan name (default: enterprise)")
    args = parser.parse_args()

    passphrase = getpass.getpass("Passphrase: ")
    if not passphrase:
        raise SystemExit("ERROR: passphrase required")

    try:
        private_key = derive_private_key(passphrase)
    except Exception as e:
        raise SystemExit(f"ERROR: {e}") from e

    exp = int(time.time()) + args.days * 86400
    payload = {
        "org_id": args.org,
        "features": args.features,
        "exp": exp,
        "plan": args.plan,
    }

    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    sig_b64 = base64.urlsafe_b64encode(private_key.sign(payload_b64.encode())).decode()
    license_key = f"{payload_b64}.{sig_b64}"

    expiry = datetime.datetime.fromtimestamp(exp).strftime("%Y-%m-%d")
    print(f"\nLicense for:  {args.org}")
    print(f"Features:     {', '.join(args.features)}")
    print(f"Expires:      {expiry}")
    print(f"\nOBSERVAL_LICENSE_KEY={license_key}\n")


if __name__ == "__main__":
    main()
