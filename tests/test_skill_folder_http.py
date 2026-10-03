# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""The negotiated folder contract through the actual FastAPI route and schema."""

import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from api.deps import get_db, get_registry_user
from api.routes import skill
from models.skill import SkillDownload, SkillVersion
from services.skill_revisions import skill_content_revision
from tests import discovery_support as ds

CONTRACT = json.loads((Path(__file__).parent / "fixtures" / "skill_folder_install_contract.json").read_text())


@pytest.mark.asyncio
async def test_http_selected_skill_needs_capability_and_deliberate_rollout(monkeypatch):
    engine = ds.make_engine()
    maker = await ds.create_schema(engine)
    async with engine.begin() as conn:
        await conn.run_sync(SkillDownload.__table__.create)
    try:
        async with maker() as db:
            owner = await ds.user(db)
            listing = await ds.skill(db, owner)
            version = await db.get(SkillVersion, listing.latest_version_id)
            version.extra_files = [
                {
                    "path": "data/binary.bin",
                    "content": base64.b64encode(b"\x00\xff").decode(),
                    "encoding": "base64",
                    "executable": False,
                }
            ]
            version.content_revision = skill_content_revision(listing, version)
            await db.commit()
            listing_id, version_id = listing.id, version.id

        app = FastAPI()
        app.include_router(skill.router)

        async def session():
            async with maker() as db:
                yield db

        app.dependency_overrides[get_db] = session
        app.dependency_overrides[get_registry_user] = lambda: owner
        monkeypatch.setattr("api.routes.config.derive_endpoints", AsyncMock(return_value={"api": "https://api.test"}))
        url = f"/api/v1/skills/{listing_id}/install"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            old = await client.post(url, json={"harness": "pi", "version": "1.2.0"})
            assert old.status_code == 409
            assert old.json() == {"detail": CONTRACT["refusals"]["old_client_standalone"]["detail"]}
            opted = {"harness": "pi", "version": "1.2.0", "supported_features": ["skill_extra_files_v1"]}
            before_rollout = await client.post(url, json=opted)
            assert before_rollout.status_code == 409
            assert before_rollout.json() == {"detail": CONTRACT["refusals"]["not_rolled_out_standalone"]["detail"]}
            monkeypatch.setattr("services.dynamic_settings.get_sync_bool", lambda key, default=False: True)
            unsupported = await client.post(url, json={**opted, "harness": "kiro"})
            assert unsupported.status_code == 409
            assert unsupported.json() == {"detail": CONTRACT["refusals"]["unsupported_skills_harness"]["detail"]}
            selected = await client.post(url, json=opted)
            assert selected.status_code == 200, selected.text
            payload = selected.json()
            assert payload["bundle"]["version_id"] == str(version_id)
            assert [file["path"] for file in payload["bundle"]["files"]] == ["SKILL.md", "data/binary.bin"]
            binary = payload["bundle"]["files"][1]
            assert base64.b64decode(binary["content"]) == b"\x00\xff"
            assert binary["mode"] == "0644"
        async with maker() as db:
            version = await db.get(SkillVersion, version_id)
            assert version.download_count == 1
            assert (
                (await db.execute(select(SkillDownload).where(SkillDownload.listing_id == listing_id))).scalars().all()
            )
    finally:
        await engine.dispose()
