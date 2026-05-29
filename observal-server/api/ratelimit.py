# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from slowapi import Limiter
from starlette.requests import Request

import services.dynamic_settings as ds
from config import settings


def _get_real_ip(request: Request) -> str:
    """Return the real client IP.

    Only trusts X-Forwarded-For when the direct TCP peer is in TRUSTED_PROXY_IPS.
    Without configured trusted proxies, uses the socket IP directly.
    Supports both plain IPs and CIDR notation in the setting.
    """
    from services.shared.ip_utils import is_trusted, parse_trusted

    client_ip = request.client.host if request.client else "127.0.0.1"
    trusted_str = ds.get_sync("security.trusted_proxy_ips")
    if not trusted_str:
        return client_ip
    exact, networks = parse_trusted(trusted_str)
    if not is_trusted(client_ip, exact, networks):
        return client_ip
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return client_ip
    ips = [ip.strip() for ip in forwarded.split(",")]
    for ip in reversed(ips):
        if not is_trusted(ip, exact, networks):
            return ip
    return client_ip


limiter = Limiter(
    key_func=_get_real_ip,
    storage_uri=settings.REDIS_URL or "memory://",
    storage_options={
        "socket_connect_timeout": settings.REDIS_SOCKET_TIMEOUT,
        "socket_timeout": settings.REDIS_SOCKET_TIMEOUT,
    },
    swallow_errors=False,  # SEC-002: fail closed - Redis errors must not bypass rate limits
)
