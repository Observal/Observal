from slowapi import Limiter
from starlette.requests import Request

from config import settings


def _get_real_ip(request: Request) -> str:
    """Extract client IP, preferring X-Forwarded-For when behind a reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


limiter = Limiter(
    key_func=_get_real_ip,
    storage_uri=settings.REDIS_URL or "memory://",
    storage_options={
        "socket_connect_timeout": settings.REDIS_SOCKET_TIMEOUT,
        "socket_timeout": settings.REDIS_SOCKET_TIMEOUT,
    },
    swallow_errors=True,
)
