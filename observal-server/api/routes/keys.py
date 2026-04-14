"""API key management endpoints for multi-key support with expiration and rotation."""

import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from api.ratelimit import limiter
from config import settings
from models.api_key import ApiKey, ApiKeyEnvironment
from models.user import User
from schemas.keys import (
    KeyCreateRequest,
    KeyCreateResponse,
    KeyListResponse,
    KeyResponse,
    KeyRotateRequest,
    KeyRotateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/keys", tags=["keys"])


def _generate_api_key(environment: ApiKeyEnvironment) -> tuple[str, str, str]:
    """Generate a new API key with prefix based on environment.

    Returns:
        tuple: (full_key, sha256_hash, prefix)
    """
    # Use 43 bytes to ensure 256 bits of entropy after base64 encoding
    # (43 bytes x 6 bits/char = ~258 bits)
    random_part = secrets.token_urlsafe(43)
    prefix = f"obs_{environment.value}_"
    full_key = f"{prefix}{random_part}"
    key_hash = hmac.new(settings.SECRET_KEY.encode(), full_key.encode(), "sha256").hexdigest()
    # Store first 10 chars of full_key as display prefix
    display_prefix = full_key[:10]
    return full_key, key_hash, display_prefix


@router.post("", response_model=KeyCreateResponse, status_code=201)
@limiter.limit("5/hour")  # Prevent API key enumeration attacks
async def create_key(
    request: Request,
    req: KeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key for the authenticated user.

    The key is shown only once in the response. Users must save it securely.

    Rate limit: 5 keys per hour per IP address
    Max keys per user: 50 active keys
    """
    # Check maximum active keys per user (prevents resource exhaustion)
    active_keys_count = await db.scalar(
        select(func.count(ApiKey.id)).where(
            ApiKey.user_id == current_user.id,
            ApiKey.revoked_at.is_(None),
            (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > datetime.now(UTC)),
        )
    )

    if active_keys_count and active_keys_count >= 50:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "max_keys_exceeded",
                "message": "Maximum of 50 active API keys allowed per user.",
                "docs_url": "https://docs.observal.io/api-keys#limits",
            },
        )

    # Generate the key
    full_key, key_hash, prefix = _generate_api_key(req.environment)

    # Calculate expiration
    expires_at = None
    if req.expires_in_days is not None:
        expires_at = datetime.now(UTC) + timedelta(days=req.expires_in_days)
    elif settings.API_KEY_DEFAULT_TTL_DAYS:
        expires_at = datetime.now(UTC) + timedelta(days=settings.API_KEY_DEFAULT_TTL_DAYS)

    # Create API key record
    api_key = ApiKey(
        user_id=current_user.id,
        name=req.name,
        key_hash=key_hash,
        prefix=prefix,
        environment=req.environment,
        expires_at=expires_at,
    )

    db.add(api_key)
    try:
        await db.commit()
        await db.refresh(api_key)
    except IntegrityError as e:
        await db.rollback()
        # Check if it's duplicate name constraint
        if "uq_api_keys_user_name" in str(e):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "duplicate_key_name",
                    "message": f"A key named '{req.name}' already exists. Choose a different name.",
                    "docs_url": "https://docs.observal.io/api-keys#create",
                },
            )
        raise HTTPException(status_code=400, detail="Failed to create API key")

    logger.info(f"Created API key {api_key.id} for user {current_user.id}")

    return KeyCreateResponse(
        key=full_key,  # SHOWN ONCE
        id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        environment=api_key.environment,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
    )


@router.get("", response_model=KeyListResponse)
async def list_keys(
    status: Literal["active", "inactive", "all"] | None = Query(None, description="Filter by status"),
    environment: ApiKeyEnvironment | None = Query(None, description="Filter by environment"),
    sort: Literal["last_used_at", "created_at", "name"] = Query("created_at", description="Sort field"),
    limit: int = Query(50, ge=1, le=100, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List API keys for the authenticated user with pagination and filtering.

    Authorization: Only returns keys belonging to the current user.
    """
    # Build query with authorization check
    query = select(ApiKey).where(ApiKey.user_id == current_user.id)

    # Apply filters
    if status == "active":
        now = datetime.now(UTC)
        query = query.where((ApiKey.revoked_at.is_(None)) & ((ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now)))
    elif status == "inactive":
        now = datetime.now(UTC)
        query = query.where(
            (ApiKey.revoked_at.isnot(None)) | ((ApiKey.expires_at.isnot(None)) & (ApiKey.expires_at <= now))
        )

    if environment:
        query = query.where(ApiKey.environment == environment)

    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply sorting
    if sort == "last_used_at":
        query = query.order_by(ApiKey.last_used_at.desc().nullslast())
    elif sort == "name":
        query = query.order_by(ApiKey.name)
    else:  # created_at
        query = query.order_by(ApiKey.created_at.desc())

    # Apply pagination
    query = query.limit(limit).offset(offset)

    # Execute query
    result = await db.execute(query)
    keys = result.scalars().all()

    return KeyListResponse(
        keys=[
            KeyResponse(
                id=key.id,
                name=key.name,
                prefix=key.prefix,
                environment=key.environment,
                created_at=key.created_at,
                expires_at=key.expires_at,
                last_used_at=key.last_used_at,
                last_used_ip=key.last_used_ip,
                revoked_at=key.revoked_at,
            )
            for key in keys
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API key immediately.

    Authorization: Users can only revoke their own keys.
    """
    # Lookup key with authorization check
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "key_not_found",
                "message": "API key not found or already deleted.",
                "docs_url": "https://docs.observal.io/api-keys#revoke",
            },
        )

    # Revoke the key
    api_key.revoked_at = datetime.now(UTC)
    await db.commit()

    logger.info(f"Revoked API key {key_id} for user {current_user.id}")

    return None  # 204 No Content


@router.post("/{key_id}/rotate", response_model=KeyRotateResponse)
async def rotate_key(
    key_id: str,
    req: KeyRotateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rotate an API key with configurable grace period.

    Authorization: Users can only rotate their own keys.
    """
    # Lookup key with authorization check
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id))
    old_key = result.scalar_one_or_none()

    if not old_key:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "key_not_found",
                "message": "API key not found.",
                "docs_url": "https://docs.observal.io/api-keys#rotate",
            },
        )

    # Cannot rotate a revoked key
    if old_key.revoked_at:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "cannot_rotate_revoked",
                "message": "Cannot rotate a revoked key. Create a new key instead.",
                "docs_url": "https://docs.observal.io/api-keys#rotate",
            },
        )

    # Generate new key with same name and environment
    full_key, key_hash, prefix = _generate_api_key(old_key.environment)

    # Create new key
    new_key = ApiKey(
        user_id=current_user.id,
        name=old_key.name,  # Keep same name
        key_hash=key_hash,
        prefix=prefix,
        environment=old_key.environment,
        expires_at=old_key.expires_at,  # Keep same expiration
    )

    db.add(new_key)

    # Handle old key based on immediate flag
    if req.immediate:
        # Immediate revocation
        old_key.revoked_at = datetime.now(UTC)
        old_key_expires_at = datetime.now(UTC)
    else:
        # Set grace period expiration
        grace_period_hours = req.grace_period_hours or 24  # Default 24 hours
        old_key_expires_at = datetime.now(UTC) + timedelta(hours=grace_period_hours)
        old_key.expires_at = old_key_expires_at

    await db.commit()
    await db.refresh(new_key)

    logger.info(
        f"Rotated API key {key_id} for user {current_user.id}, "
        f"new key {new_key.id}, grace period: {req.grace_period_hours or 24}h, "
        f"immediate: {req.immediate}"
    )

    return KeyRotateResponse(
        new_key=full_key,  # SHOWN ONCE
        new_key_id=new_key.id,
        old_key_id=old_key.id,
        old_key_expires_at=old_key_expires_at,
        grace_period_hours=req.grace_period_hours or 24,
    )
