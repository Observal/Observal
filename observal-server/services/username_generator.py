# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Auto-generate unique usernames from email addresses."""

import hashlib
import re

from loguru import logger as optic
from sqlalchemy.ext.asyncio import AsyncSession

from services.registry_namespace import validate_namespace
from services.teamspace import reserve_handle


async def generate_unique_username(
    email: str,
    db: AsyncSession,
    max_attempts: int = 10,
    *,
    explicit: str | None = None,
) -> str:
    """Return a username unique across users and teams.

    When ``explicit`` is provided, validate it and confirm it is free in both
    the users and teams handle pools; raise ValueError on collision. Otherwise
    derive a base from the email and append deterministic suffixes until a free
    handle is found.
    """
    optic.trace("generating unique username from email")
    email_lower = email.lower().strip()

    if explicit:
        # reserve_handle slugifies, validates, and checks both pools.
        return await reserve_handle(db, explicit)

    base = email_lower.split("@")[0]
    base = re.sub(r"[^a-z0-9\-]", "-", base)
    base = re.sub(r"-+", "-", base).strip("-")
    base = base[:20]
    if not base or base[0] == "-" or base[-1] == "-":
        base = "user"

    # Try the cleaned base, then deterministic suffixes, all through the shared
    # cross-table reservation check.
    try:
        base = validate_namespace(base)
    except ValueError:
        pass
    else:
        try:
            return await reserve_handle(db, base)
        except ValueError:
            pass

    for attempt in range(max_attempts):
        suffix = hashlib.sha256(f"{email_lower}-{attempt}".encode()).hexdigest()[:6]
        candidate = f"{base}-{suffix}"[:32]
        try:
            return await reserve_handle(db, candidate)
        except ValueError:
            continue

    candidate = f"user-{hashlib.sha256(f'{email_lower}-fallback'.encode()).hexdigest()[:8]}"
    try:
        return await reserve_handle(db, candidate)
    except ValueError as exc:
        raise RuntimeError(f"Could not generate a unique username after {max_attempts} attempts for {email!r}") from exc
