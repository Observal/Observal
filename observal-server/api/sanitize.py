# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Input sanitization utilities for SQL-safe query construction."""


def escape_like(value: str) -> str:
    """Escape SQL LIKE/ILIKE wildcard characters in user input.

    Prevents LIKE injection by escaping %, _, and \\ so user-supplied
    strings are treated as literals inside LIKE patterns.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
