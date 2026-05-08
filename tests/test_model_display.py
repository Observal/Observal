"""Parity test for model display helpers across server and CLI.

Server-side ``services.model_display.format_display`` and CLI-side
``observal_cli.render.format_model`` must produce identical output for every
case in ``tests/fixtures/model_display_cases.json``. The TypeScript helper
under ``web/src/lib/model-display.ts`` is exercised by frontend unit tests.
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
def test_cli_display_matches_fixture(case):
    from observal_cli.render import format_model

    row = {
        "display_name": case["display_name"],
        "model_id": case["model_id"],
        "release_date": case.get("release_date"),
    }
    primary, secondary, is_rolling = format_model(row, disambiguate=case["disambiguate"])
    expected = case["expected"]
    assert primary == expected["primary"], f"{case['name']}: primary mismatch"
    assert secondary == expected["secondary"], f"{case['name']}: secondary mismatch"
    assert is_rolling == expected["is_rolling"], f"{case['name']}: is_rolling mismatch"
