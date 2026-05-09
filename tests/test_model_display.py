"""Parity test for model display helpers.

Server-side ``services.model_display.format_display`` is the source of truth.
CLI-side ``observal_cli.render.format_model`` reads the pre-computed ``display``
field from the API response. This test verifies both paths produce the same
output for every case in ``tests/fixtures/model_display_cases.json``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "model_display_cases.json"


def _load_cases() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["cases"]


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["name"])
def test_server_display_matches_fixture(case):
    from services.model_display import format_display

    rd_value = case.get("release_date")
    rd = date.fromisoformat(rd_value) if rd_value else None
    primary, secondary, is_rolling = format_display(
        display_name=case["display_name"],
        model_id=case["model_id"],
        release_date=rd,
        disambiguate=case["disambiguate"],
    )
    expected = case["expected"]
    assert primary == expected["primary"], f"{case['name']}: primary mismatch"
    assert secondary == expected["secondary"], f"{case['name']}: secondary mismatch"
    assert is_rolling == expected["is_rolling"], f"{case['name']}: is_rolling mismatch"


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["name"])
def test_cli_reads_server_display_field(case):
    """CLI format_model reads the pre-computed display field from the API response."""
    from observal_cli.render import format_model

    # Simulate what the server sends: pre-computed display from format_display
    from services.model_display import format_display

    rd_value = case.get("release_date")
    rd = date.fromisoformat(rd_value) if rd_value else None
    server_primary, server_secondary, server_rolling = format_display(
        display_name=case["display_name"],
        model_id=case["model_id"],
        release_date=rd,
        disambiguate=case["disambiguate"],
    )

    # Build a row as it would arrive from the API (with display field)
    row = {
        "display_name": case["display_name"],
        "model_id": case["model_id"],
        "release_date": case.get("release_date"),
        "display": {
            "primary": server_primary,
            "secondary": server_secondary,
            "is_rolling": server_rolling,
        },
    }
    primary, secondary, is_rolling = format_model(row, disambiguate=case["disambiguate"])
    expected = case["expected"]
    assert primary == expected["primary"], f"{case['name']}: primary mismatch"
    assert secondary == expected["secondary"], f"{case['name']}: secondary mismatch"
    assert is_rolling == expected["is_rolling"], f"{case['name']}: is_rolling mismatch"
