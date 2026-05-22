# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared helpers for admin route sub-modules."""

import base64
import hashlib
import re
import secrets

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.organization import Organization
from models.user import User

# ── Branding Validation ──────────────────────────────────

_ALLOWED_LOGO_MIMES = {
    "image/png",
    "image/svg+xml",
    "image/x-icon",
    "image/vnd.microsoft.icon",
    "image/jpeg",
    "image/webp",
}
_MAX_LOGO_BYTES = 2 * 1024 * 1024
_MAX_DATA_URL_LEN = 3 * 1024 * 1024  # base64 bloats ~33%, cap raw string
_MAX_APP_NAME_LEN = 30

# Magic byte signatures for allowed image formats
_MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/webp": [b"RIFF"],  # RIFF....WEBP
    "image/x-icon": [b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"],
    "image/vnd.microsoft.icon": [b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"],
    # SVG is validated separately via _sanitize_svg
}

# SVG elements and attributes that can execute code or make external requests
_SVG_DANGEROUS_TAGS = re.compile(
    r"<[\s/]*(script|foreignObject|iframe|embed|object|applet|meta|link|style|handler|set|animate|animateTransform|animateMotion)\b",
    re.IGNORECASE,
)
_SVG_EVENT_ATTRS = re.compile(r"\bon\w+\s*=", re.IGNORECASE)
_SVG_JS_HREF = re.compile(r"(?:href|xlink:href)[\s=\"']*javascript:", re.IGNORECASE)
_SVG_EXTERNAL_REF = re.compile(r"(?:href|xlink:href|src|url)[\s=\"']*(?:https?://|//|data:(?!image/))", re.IGNORECASE)
_SVG_XML_DECL = re.compile(r"<!(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)

# Characters forbidden in the app name
_UNSAFE_NAME_CHARS = re.compile("[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


def _validate_magic_bytes(raw: bytes, mime_type: str) -> None:
    """Verify the file's actual bytes match the claimed MIME type."""
    signatures = _MAGIC_BYTES.get(mime_type)
    if signatures is None:
        return  # SVG handled separately
    if not any(raw.startswith(sig) for sig in signatures):
        raise HTTPException(status_code=422, detail=f"File content does not match declared type {mime_type}")
    if mime_type == "image/webp" and raw[8:12] != b"WEBP":
        raise HTTPException(status_code=422, detail="File content does not match declared type image/webp")


def _sanitize_svg(raw: bytes) -> bytes:
    """Reject SVGs containing dangerous elements or attributes."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="SVG contains invalid UTF-8")

    if _SVG_XML_DECL.search(text):
        raise HTTPException(status_code=422, detail="SVG must not contain DOCTYPE or ENTITY declarations")
    if _SVG_DANGEROUS_TAGS.search(text):
        raise HTTPException(
            status_code=422, detail="SVG contains forbidden elements (script, foreignObject, iframe, etc.)"
        )
    if _SVG_EVENT_ATTRS.search(text):
        raise HTTPException(
            status_code=422, detail="SVG contains forbidden event handler attributes (onclick, onload, etc.)"
        )
    if _SVG_JS_HREF.search(text):
        raise HTTPException(status_code=422, detail="SVG contains javascript: URLs")
    if _SVG_EXTERNAL_REF.search(text):
        raise HTTPException(status_code=422, detail="SVG contains external resource references")

    return raw


def _validate_branding_logo(value: str) -> None:
    if not value:
        return

    if len(value) > _MAX_DATA_URL_LEN:
        raise HTTPException(status_code=422, detail="Image data too large")

    match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", value, re.DOTALL)
    if not match:
        raise HTTPException(status_code=422, detail="Logo must be a base64 data URL (data:image/...;base64,...)")
    mime_type = match.group(1)
    b64_data = match.group(2)
    if mime_type not in _ALLOWED_LOGO_MIMES:
        raise HTTPException(
            status_code=422, detail=f"Unsupported image type: {mime_type}. Allowed: PNG, SVG, ICO, JPEG, WEBP"
        )
    try:
        raw = base64.b64decode(b64_data)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid base64 data")
    if len(raw) > _MAX_LOGO_BYTES:
        size_mb = round(len(raw) / (1024 * 1024), 1)
        max_mb = _MAX_LOGO_BYTES // (1024 * 1024)
        raise HTTPException(status_code=422, detail=f"Logo too large ({size_mb}MB). Maximum: {max_mb}MB")

    if mime_type == "image/svg+xml":
        _sanitize_svg(raw)
    else:
        _validate_magic_bytes(raw, mime_type)


def _validate_branding_app_name(value: str) -> None:
    if len(value) > _MAX_APP_NAME_LEN:
        raise HTTPException(
            status_code=422, detail=f"App name too long ({len(value)} chars). Maximum: {_MAX_APP_NAME_LEN}"
        )
    if _UNSAFE_NAME_CHARS.search(value):
        raise HTTPException(status_code=422, detail="App name contains forbidden control or invisible characters")
    if "<" in value and ">" in value:
        raise HTTPException(status_code=422, detail="App name must not contain HTML tags")


# ── Enterprise Settings ──────────────────────────────────


async def _generate_unique_password(db: AsyncSession, length: int = 20, max_attempts: int = 10) -> str:
    """Generate a secure password whose hash doesn't collide with any existing password hash."""
    import os
    import string

    alphabet = string.ascii_letters + string.digits + string.punctuation
    result = await db.execute(select(User.password_hash).where(User.password_hash.is_not(None)))
    existing_hashes = {row[0] for row in result.all()}

    for _ in range(max_attempts):
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        # Check against all existing password hashes
        salt = os.urandom(16)
        key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
        candidate_hash = f"{salt.hex()}${key.hex()}"
        if candidate_hash not in existing_hashes:
            return password

    # Astronomically unlikely to reach here, but be safe
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _get_user_org(db: AsyncSession, user: User) -> Organization:
    """Get the user's org. Raises 400 if user has no org."""
    if not user.org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = (await db.execute(select(Organization).where(Organization.id == user.org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org
