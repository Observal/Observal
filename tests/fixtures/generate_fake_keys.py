# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Regenerate tests/fixtures/fake_api_keys.json.

Source of truth for the 500 deterministic fake API keys consumed by
tests/test_encryption_fake_keys.py. All keys are FAKE, derived from a fixed
seed via SHA-512; none are real credentials. The fixture filename and this
script both contain 'fake' so the gitleaks allowlist skips them.

Run from repo root:

    python tests/fixtures/generate_fake_keys.py

Writes tests/fixtures/fake_api_keys.json in place. Exits non-zero if the
generated count is not exactly 500.
"""

from __future__ import annotations

import hashlib
import json
import string
from pathlib import Path

_RNG_SEED = "observal-test-fake-keys-seed-2026"
_FIXTURE = Path(__file__).parent / "fake_api_keys.json"
_EXPECTED_COUNT = 500


def _deterministic_hex(index: int, length: int) -> str:
    h = hashlib.sha512(f"{_RNG_SEED}:{index}".encode()).hexdigest()
    return h[:length]


def _deterministic_alnum(index: int, length: int) -> str:
    h = ""
    for block in range((length * 2 // 128) + 1):
        h += hashlib.sha512(f"{_RNG_SEED}:alnum:{index}:{block}".encode()).hexdigest()
    chars = string.ascii_letters + string.digits
    return "".join(chars[int(h[i : i + 2], 16) % len(chars)] for i in range(0, length * 2, 2))


def _deterministic_base64ish(index: int, length: int) -> str:
    h = ""
    for block in range((length * 2 // 128) + 1):
        h += hashlib.sha512(f"{_RNG_SEED}:b64:{index}:{block}".encode()).hexdigest()
    chars = string.ascii_letters + string.digits + "+/"
    return "".join(chars[int(h[i : i + 2], 16) % len(chars)] for i in range(0, length * 2, 2))


def build_keys() -> list[tuple[str, str]]:
    """500 fake keys across 25 provider formats, 20 per provider."""
    keys: list[tuple[str, str]] = []

    # Round 1: 13 formats.
    for i in range(20):
        keys.append(("openai", f"sk-{_deterministic_alnum(i, 48)}"))
    for i in range(20):
        keys.append(("openai_project", f"sk-proj-{_deterministic_alnum(100 + i, 44)}"))
    for i in range(20):
        keys.append(("anthropic", f"sk-ant-api03-{_deterministic_base64ish(200 + i, 80)}"))
    for i in range(20):
        keys.append(("openrouter", f"sk-or-v1-{_deterministic_hex(300 + i, 64)}"))
    for i in range(20):
        keys.append(("google_ai", f"AIza{_deterministic_alnum(400 + i, 35)}"))
    for i in range(20):
        keys.append(("aws_access_key", f"AKIA{_deterministic_alnum(500 + i, 16).upper()}"))
    for i in range(20):
        keys.append(("aws_secret_key", _deterministic_base64ish(600 + i, 40)))
    for i in range(20):
        keys.append(("cohere", _deterministic_alnum(700 + i, 40)))
    for i in range(20):
        keys.append(("mistral", _deterministic_alnum(800 + i, 48)))
    for i in range(20):
        keys.append(("huggingface", f"hf_{_deterministic_alnum(900 + i, 34)}"))
    for i in range(20):
        keys.append(("replicate", f"r8_{_deterministic_alnum(1000 + i, 37)}"))
    for i in range(20):
        keys.append(("together", _deterministic_hex(1100 + i, 64)))
    for i in range(20):
        keys.append(("groq", f"gsk_{_deterministic_alnum(1200 + i, 52)}"))

    # Round 2: 12 more formats, sourced from primary provider docs.
    for i in range(20):
        keys.append(("github_pat_classic", f"ghp_{_deterministic_alnum(1300 + i, 36)}"))
    for i in range(20):
        keys.append(("github_pat_finegrained", f"github_pat_{_deterministic_alnum(1400 + i, 82)}"))
    for i in range(20):
        keys.append(("gitlab_pat", f"glpat-{_deterministic_alnum(1500 + i, 20)}"))
    for i in range(20):
        keys.append(
            (
                "slack_bot",
                f"xoxb-{_deterministic_alnum(1600 + i, 11)}-"
                f"{_deterministic_alnum(1650 + i, 11)}-"
                f"{_deterministic_alnum(1690 + i, 24)}",
            )
        )
    for i in range(20):
        keys.append(("stripe_secret", f"sk_live_{_deterministic_alnum(1700 + i, 50)}"))
    for i in range(20):
        keys.append(("twilio_sid", f"AC{_deterministic_hex(1800 + i, 32).upper()}"))
    for i in range(20):
        keys.append(
            (
                "sendgrid",
                f"SG.{_deterministic_alnum(1900 + i, 22)}.{_deterministic_alnum(1950 + i, 43)}",
            )
        )
    for i in range(20):
        keys.append(("notion", f"ntn_{_deterministic_alnum(2100 + i, 50)}"))
    for i in range(20):
        keys.append(("linear", f"lin_api_{_deterministic_alnum(2200 + i, 40)}"))
    for i in range(20):
        keys.append(("vercel", f"vcp_{_deterministic_alnum(2300 + i, 24)}"))
    for i in range(20):
        keys.append(("digitalocean", f"dop_v1_{_deterministic_hex(2400 + i, 64)}"))
    for i in range(20):
        keys.append(("mailgun", f"key-{_deterministic_hex(2500 + i, 32)}"))

    return keys


def main() -> int:
    keys = build_keys()
    assert len(keys) == _EXPECTED_COUNT, f"Expected {_EXPECTED_COUNT} keys, got {len(keys)}"
    payload = [{"provider": p, "key": k} for p, k in keys]
    _FIXTURE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(keys)} fake keys to {_FIXTURE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
