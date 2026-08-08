# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""The return-path (`next`) validator must reject every open-redirect vector.

`_is_safe_next` is the server half of the relative-only rule; web/src/lib/safe-next.ts
is the client mirror and must stay in lockstep. Control characters matter because a
browser strips tab/newline/CR before resolving a URL, so "/\\n/evil.com" — which
passes a naive leading-slash check — collapses to a protocol-relative "//evil.com".
"""

import pytest

from api.routes.auth import _is_safe_next

SAFE = [
    "/",
    "/teamspaces/acme",
    "/agents/ns/slug?tab=x",
    "/components/skills/ns/slug",
]

UNSAFE = [
    None,
    "",
    "//evil.com",
    "///evil.com",
    "https://evil.com",
    "http://evil.com",
    "\\evil.com",
    "/\\evil.com",
    "/\\/evil.com",
    "javascript:alert(1)",
    "evil.com",
    "/\tevil.com",  # tab
    "/\nevil.com",  # newline
    "/\revil.com",  # carriage return
    "/\n//evil.com",  # newline then protocol-relative
    "/\x00/evil.com",  # NUL
    "/\x85/evil.com",  # NEL (C1 control)
]


@pytest.mark.parametrize("path", SAFE)
def test_safe_paths_accepted(path):
    assert _is_safe_next(path) is True


@pytest.mark.parametrize("path", UNSAFE)
def test_unsafe_paths_rejected(path):
    assert _is_safe_next(path) is False
