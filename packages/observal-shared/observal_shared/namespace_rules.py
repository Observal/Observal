# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Canonical registry namespace charset, shared by the server and the CLI.

A namespace is a user's handle and the left half of a qualified identity
(``namespace/slug``). The rule lived in three places that had to agree — the
server validator plus client-side pre-checks — so it lives here instead. The
web UI keeps its own copy in ``web/src/lib/registry-name.ts``; keep the two in
sync when this changes.
"""

from __future__ import annotations

import re

#: 3-32 characters, starting and ending alphanumeric, hyphens and dots inside.
NAMESPACE_PATTERN = r"^[a-z0-9][a-z0-9.-]{1,30}[a-z0-9]$"
NAMESPACE_RE = re.compile(NAMESPACE_PATTERN)

#: Human-readable form of the rule, reused in error messages on both sides.
NAMESPACE_RULE_TEXT = (
    "Namespaces must be 3-32 characters using lowercase letters, numbers, "
    "hyphens, and dots, and must start and end with a letter or number"
)


def is_valid_namespace(handle: str | None) -> bool:
    """Whether ``handle`` can be used verbatim as a registry namespace."""
    if not handle:
        return False
    value = handle.strip().lower()
    if ".." in value:
        return False
    return NAMESPACE_RE.fullmatch(value) is not None
