"""Per-request context propagation via contextvars.

Populates IP, user agent, HTTP method, and path so that downstream code
(including ee/ audit handlers) can access request metadata without
requiring an explicit ``Request`` parameter.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import NamedTuple

_request_ip: ContextVar[str] = ContextVar("request_ip", default="")
_request_user_agent: ContextVar[str] = ContextVar("request_user_agent", default="")
_request_method: ContextVar[str] = ContextVar("request_method", default="")
_request_path: ContextVar[str] = ContextVar("request_path", default="")


class RequestContext(NamedTuple):
    ip: str
    user_agent: str
    method: str
    path: str


def set_request_context(request) -> None:
    """Populate contextvars from a Starlette/FastAPI Request."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "127.0.0.1"

    _request_ip.set(ip)
    _request_user_agent.set(request.headers.get("user-agent", ""))
    _request_method.set(request.method)
    _request_path.set(request.url.path)


def get_request_context() -> RequestContext:
    """Read the current request context from contextvars."""
    return RequestContext(
        ip=_request_ip.get(),
        user_agent=_request_user_agent.get(),
        method=_request_method.get(),
        path=_request_path.get(),
    )
