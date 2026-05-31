# SPDX-FileCopyrightText: 2026 Nav-Prak <naveenprakaasam@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Org ingest privacy-mode setting: validation and admin get/set endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from models.user import UserRole
from services.privacy import DEFAULT_PRIVACY_MODE, PRIVACY_MODES, normalize_privacy_mode


def _admin(org_id=None):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "admin@example.com"
    user.role = UserRole.admin
    user.org_id = org_id
    return user


def _db_returning(org):
    result = MagicMock()
    result.scalar_one_or_none.return_value = org
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


def test_normalize_privacy_mode_defaults_to_full():
    assert DEFAULT_PRIVACY_MODE == "full"
    assert normalize_privacy_mode("redacted") == "redacted"
    assert normalize_privacy_mode("metadata_only") == "metadata_only"
    assert normalize_privacy_mode("disabled_raw") == "disabled_raw"
    assert normalize_privacy_mode("bogus") == "full"
    assert normalize_privacy_mode(None) == "full"
    assert set(PRIVACY_MODES) == {"full", "redacted", "metadata_only", "disabled_raw"}


@pytest.mark.asyncio
async def test_set_privacy_mode_persists_valid_mode():
    from api.routes.admin.org import set_privacy_mode

    org = MagicMock()
    org.id = uuid.uuid4()
    db = _db_returning(org)

    with patch("api.routes.admin.org.emit_security_event", new=AsyncMock()):
        result = await set_privacy_mode(req={"privacy_mode": "metadata_only"}, db=db, current_user=_admin(org.id))

    assert result == {"privacy_mode": "metadata_only"}
    assert org.privacy_mode == "metadata_only"
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_set_privacy_mode_rejects_unknown_mode():
    from api.routes.admin.org import set_privacy_mode

    db = _db_returning(MagicMock())
    with pytest.raises(HTTPException) as exc:
        await set_privacy_mode(req={"privacy_mode": "bogus"}, db=db, current_user=_admin(uuid.uuid4()))
    assert exc.value.status_code == 422
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_privacy_mode_requires_org():
    from api.routes.admin.org import set_privacy_mode

    db = _db_returning(MagicMock())
    with pytest.raises(HTTPException) as exc:
        await set_privacy_mode(req={"privacy_mode": "full"}, db=db, current_user=_admin(None))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_get_privacy_mode_returns_org_mode_and_available():
    from api.routes.admin.org import get_privacy_mode

    org = MagicMock()
    org.privacy_mode = "disabled_raw"
    db = _db_returning(org)

    result = await get_privacy_mode(db=db, current_user=_admin(uuid.uuid4()))

    assert result["privacy_mode"] == "disabled_raw"
    assert set(result["available_modes"]) == set(PRIVACY_MODES)
