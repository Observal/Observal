"""Request ID middleware.

Assigns a unique UUID to every request and returns it via the ``X-Request-ID``
response header.  If the client supplies a valid UUID in the ``X-Request-ID``
request header it is reused; otherwise a new one is generated.  Invalid values
are silently replaced to prevent header injection.

The request ID is also bound to the structlog context so that every log line
emitted during the request carries it automatically.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

from services.request_context import set_request_context

if TYPE_CHECKING:
    from starlette.requests import Request


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach an ``X-Request-ID`` header to every response and bind it to the structlog context."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id")
        request_id: str

        if incoming:
            try:
                request_id = str(uuid.UUID(incoming))
            except (ValueError, AttributeError):
                request_id = str(uuid.uuid4())
        else:
            request_id = str(uuid.uuid4())

        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        set_request_context(request)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
