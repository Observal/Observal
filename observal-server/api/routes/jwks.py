# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""JWKS discovery endpoint for JWT public key distribution.

Exposes the server's public signing key(s) in standard JWKS format so that
clients and browsers can verify tokens without a shared secret.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.crypto import get_key_manager

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/.well-known/jwks.json")
async def jwks() -> JSONResponse:
    """Return the server's public signing keys in JWKS format (RFC 7517).

    Clients use this endpoint to obtain the public key(s) needed to verify
    JWTs issued by this server.  During key rotation, both the current and
    recently retired keys are included so in-flight tokens remain valid.
    """
    km = get_key_manager()
    return JSONResponse(
        content=km.get_jwks(),
        headers={"Cache-Control": "public, max-age=3600"},
    )
