# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Auto-generate unique usernames from email addresses."""

import hashlib
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User

# Same pattern as validation
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,30}[a-z0-9]$")


async def generate_unique_username(
    email: str,
    db: AsyncSession,
    max_attempts: int = 10,
) -> str:
    """Generate a unique username from email with collision handling.

    Algorithm:
    1. Extract base from email (before @)
    2. Sanitize: lowercase, replace invalid chars with hyphens
    3. Try base name if it passes validation (e.g., "john.doe@example.com" → "john-doe")
    4. If taken, append deterministic suffix (e.g., "john-doe-a1b2c3")
    5. Suffix uses SHA256(email + attempt)[:6] for deterministic uniqueness

    Returns a valid username that passes USERNAME_RE validation and is unique in DB.
    """
    # Extract and sanitize base
    email_lower = email.lower().strip()
    base = email_lower.split("@")[0]  # Get part before @

    # Replace invalid chars: dots, underscores, spaces → hyphens
    # Keep only alphanumeric and hyphens
    base = re.sub(r"[^a-z0-9\-]", "-", base)
    # Remove leading/trailing hyphens and collapse multiple hyphens
    base = re.sub(r"-+", "-", base).strip("-")
    # Truncate to max reasonable length (leaving room for suffix)
    base = base[:20]

    # Ensure base is at least 1 char and doesn't start/end with hyphen
    if not base or base[0] == "-" or base[-1] == "-":
        base = "user"

    # Try base name first if it passes regex validation
    if USERNAME_RE.match(base):
        result = await db.execute(select(User.username).where(User.username == base))
        if not result.scalar_one_or_none():
            return base

    # Try with deterministic suffixes
    for attempt in range(max_attempts):
        hash_input = f"{email_lower}-{attempt}".encode()
        suffix = hashlib.sha256(hash_input).hexdigest()[:6]
        candidate = f"{base}-{suffix}"

        # Ensure we stay within 32 char limit
        if len(candidate) > 32:
            candidate = candidate[:32]

        # Verify it matches our regex
        if not USERNAME_RE.match(candidate):
            continue

        # Check if available
        result = await db.execute(select(User.username).where(User.username == candidate))
        if not result.scalar_one_or_none():
            return candidate

    # Fallback: use full hash for maximum entropy
    hash_input = f"{email_lower}-fallback".encode()
    suffix = hashlib.sha256(hash_input).hexdigest()[:8]
    candidate = f"user-{suffix}"
    result = await db.execute(select(User.username).where(User.username == candidate))
    if not result.scalar_one_or_none():
        return candidate
    # Should never be reached in practice
    raise RuntimeError(f"Could not generate a unique username after {max_attempts} attempts for {email!r}")
