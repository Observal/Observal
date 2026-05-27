# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""IP parsing and trust utilities for proxy-aware IP resolution.

Used by both TrustedProxyMiddleware and the rate limiter to determine
whether a peer IP is a trusted proxy and to resolve the real client IP
from X-Forwarded-For headers.

Supports both plain IPs and CIDR notation (e.g. "172.16.0.0/12,10.0.0.1").
Results are cached per unique setting string to avoid re-parsing on every request.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from loguru import logger as optic


@lru_cache(maxsize=4)
def parse_trusted(raw: str) -> tuple[frozenset[str], tuple]:
    """Parse the trusted proxy setting into exact IPs and CIDR networks.

    Returns a tuple of (exact_ips_frozenset, networks_tuple) for hashability.
    Cached by the raw string value so repeated calls within the same config
    epoch are essentially free.
    """
    exact: set[str] = set()
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "/" in entry:
            try:
                networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                optic.warning("invalid CIDR in security.trusted_proxy_ips: {}", entry)
        else:
            exact.add(entry)
    return frozenset(exact), tuple(networks)


def is_trusted(ip: str, exact: frozenset[str], networks: tuple) -> bool:
    """Check if an IP is trusted (exact match or within a CIDR range)."""
    if ip in exact:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)
