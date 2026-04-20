from slowapi import Limiter
from slowapi.util import get_remote_address

from config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL or "memory://",
    storage_options={
        "socket_connect_timeout": settings.REDIS_SOCKET_TIMEOUT,
        "socket_timeout": settings.REDIS_SOCKET_TIMEOUT,
    },
    swallow_errors=True,
)
