"""SCIM 2.0 user provisioning service.

Maps between SCIM Core User schema (RFC 7643) and our User model.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


def hash_scim_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def parse_scim_user(resource: dict[str, Any]) -> dict[str, Any]:
    emails = resource.get("emails", [])
    primary_email = ""
    for em in emails:
        if em.get("primary"):
            primary_email = em.get("value", "").strip().lower()
            break
    if not primary_email and emails:
        primary_email = emails[0].get("value", "").strip().lower()
    if not primary_email:
        primary_email = resource.get("userName", "").strip().lower()

    name_obj = resource.get("name", {})
    given = name_obj.get("givenName", "")
    family = name_obj.get("familyName", "")
    display = resource.get("displayName", "")
    if given and family:
        full_name = f"{given} {family}"
    elif display:
        full_name = display
    else:
        full_name = primary_email

    active = resource.get("active", True)
    return {"email": primary_email, "name": full_name, "active": active}


def format_scim_user(user, base_url: str = "") -> dict[str, Any]:
    user_id = str(user.id)
    name_parts = (user.name or "").split(" ", 1)
    given = name_parts[0] if name_parts else ""
    family = name_parts[1] if len(name_parts) > 1 else ""

    is_active = True
    if hasattr(user, "auth_provider") and user.auth_provider == "deactivated":
        is_active = False

    return {
        "schemas": [SCIM_USER_SCHEMA],
        "id": user_id,
        "userName": user.email,
        "name": {
            "givenName": given,
            "familyName": family,
            "formatted": user.name or "",
        },
        "displayName": user.name or "",
        "emails": [{"value": user.email, "primary": True, "type": "work"}],
        "active": is_active,
        "meta": {
            "resourceType": "User",
            "created": user.created_at.isoformat() if user.created_at else "",
            "location": f"{base_url}/Users/{user_id}" if base_url else "",
        },
    }


def format_scim_list(resources: list[dict], total: int, start_index: int = 1) -> dict[str, Any]:
    return {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": total,
        "itemsPerPage": len(resources),
        "startIndex": start_index,
        "Resources": resources,
    }


def format_scim_error(status: int, detail: str) -> dict[str, Any]:
    return {
        "schemas": [SCIM_ERROR_SCHEMA],
        "status": str(status),
        "detail": detail,
    }


SUPPORTED_FILTER_OPS = {"eq", "ne", "sw", "co"}
_FILTER_RE = re.compile(
    r'^(\w+(?:\.\w+)?)\s+(eq|ne|sw|co)\s+"([^"]*)"$',
    re.IGNORECASE,
)

MAX_SCIM_PAGE_SIZE = 500


class ScimFilter:
    """Parsed SCIM filter expression."""

    def __init__(self, attr: str, op: str, value: str):
        self.attr = attr.lower()
        self.op = op.lower()
        self.value = value


def parse_scim_filter(raw: str) -> ScimFilter | None:
    """Parse a simple SCIM filter expression. Returns None if unparseable."""
    if not raw or not raw.strip():
        return None
    m = _FILTER_RE.match(raw.strip())
    if not m:
        return None
    return ScimFilter(attr=m.group(1), op=m.group(2), value=m.group(3))


def validate_scim_pagination(start_index: int, count: int) -> tuple[int, int]:
    """Clamp SCIM pagination params to safe values."""
    start_index = max(1, start_index)
    count = max(0, min(count, MAX_SCIM_PAGE_SIZE))
    return start_index, count
