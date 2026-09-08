# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Canonical Registry slug rules shared by server and CLI clients."""

from __future__ import annotations

import re

SLUG_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
SLUG_RE = re.compile(SLUG_PATTERN)
RESERVED_SLUGS = frozenset({"archive", "draft", "install", "resolve", "restore", "submit", "unarchive", "versions"})


def validate_slug(slug: str, *, allow_reserved: bool = False) -> str:
    value = slug.strip().lower()
    if not SLUG_RE.fullmatch(value):
        raise ValueError(
            "Slug must be at most 64 characters, start with a letter or number, "
            "and contain only lowercase letters, numbers, hyphens, and underscores"
        )
    if not allow_reserved and value in RESERVED_SLUGS:
        raise ValueError(f"Slug '{value}' is reserved")
    return value


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-_")
    if not slug:
        raise ValueError("Name must contain at least one letter or number")
    if not slug[0].isalnum():
        slug = f"item-{slug}"
    slug = slug[:64].rstrip("-_")
    return validate_slug(slug)
