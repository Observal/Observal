# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Dhanpraja <dhanpraja231@users.noreply.github.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 shreyansh-web <shreyansh487@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Registry-backed harness model tests."""

from __future__ import annotations

import pytest


def test_every_harness_has_model_catalog():
    from observal_shared.harness_models import supported_model_ids
    from observal_shared.harness_registry import HARNESS_REGISTRY

    for harness, spec in HARNESS_REGISTRY.items():
        assert spec["model_catalog_file"] == f"harness_models/{harness}.json"
        assert spec["supported_models"] == supported_model_ids(harness)
        assert spec["supported_models"], f"{harness} has no supported models"


def test_dynamic_catalogs_have_expected_sources():
    from observal_shared.harness_models import harness_models

    assert len(harness_models("pi")["models"]) >= 900
    assert any(row["id"].startswith("opencode/") for row in harness_models("opencode")["models"])
    assert any(row["id"] == "gemini-enterprise:<model-id>" for row in harness_models("antigravity")["models"])


def test_cli_catalog_filters_by_harness():
    from observal_cli import model_catalog

    rows = model_catalog.fetch_catalog(harness="claude-code")["models"]
    assert rows
    assert {row["harness"] for row in rows} == {"claude-code"}
    assert any(row["model_id"] == "sonnet" for row in rows)


def test_cli_catalog_rejects_unknown_harness():
    from observal_cli import model_catalog

    with pytest.raises(ValueError, match="Unknown harness 'claude'"):
        model_catalog.fetch_catalog(harness="claude")


@pytest.mark.asyncio
async def test_resolver_validates_against_harness_registry():
    from services.model_resolver import resolve_model_for_harness

    emitted, warnings = await resolve_model_for_harness("kiro", models_by_harness={"kiro": "claude-sonnet-4-6"})
    assert emitted == "claude-sonnet-4.6"
    assert warnings == []

    emitted, warnings = await resolve_model_for_harness("kiro", models_by_harness={"kiro": "not-real"})
    assert emitted is None
    assert "not in the kiro harness registry" in warnings[0]


@pytest.mark.asyncio
async def test_resolver_allows_provider_source_patterns():
    from services.model_resolver import resolve_model_for_harness

    emitted, warnings = await resolve_model_for_harness(
        "opencode", models_by_harness={"opencode": "anthropic/claude-sonnet-4-6"}
    )
    assert emitted == "anthropic/claude-sonnet-4-6"
    assert warnings == []
