# SPDX-License-Identifier: AGPL-3.0-only

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _looks_like_unique_violation(exc: IntegrityError) -> bool:
    text = f"{exc} {getattr(exc, 'orig', '')}".lower()
    return any(token in text for token in ("duplicate key", "unique constraint", "unique violation"))


async def raise_listing_integrity_error(
    db: AsyncSession,
    listing_type: str,
    listing_name: str,
    exc: IntegrityError,
) -> None:
    await db.rollback()
    if _looks_like_unique_violation(exc):
        raise HTTPException(
            status_code=409,
            detail=f"A {listing_type} listing named '{listing_name}' already exists",
        ) from exc
    raise exc
