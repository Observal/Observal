# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Registry-backed harness model catalog for the CLI."""

from __future__ import annotations


def _catalogs() -> dict[str, dict]:
    from observal_shared.harness_models import all_harness_models

    return all_harness_models()


def valid_harnesses() -> list[str]:
    return sorted(_catalogs())


def fetch_catalog(*, refresh: bool = False, harness: str | None = None, ttl: int = 0) -> dict:
    del refresh, ttl
    catalogs = _catalogs()
    selected = [harness] if harness else valid_harnesses()
    unknown = [name for name in selected if name not in catalogs]
    if unknown:
        raise ValueError(f"Unknown harness '{unknown[0]}'. Valid harnesses: {', '.join(valid_harnesses())}")

    rows = []
    for name in selected:
        data = catalogs[name]
        for row in data.get("models", []):
            rows.append(
                {**row, "harness": data["harness"], "model_id": row["id"], "display_name": row.get("label", row["id"])}
            )
    return {"models": rows, "source": "harness-registry", "degraded": False}


def model_choices_for_picker(catalog: dict, harness: str) -> list[tuple[str, str]]:
    return [
        (m["model_id"], m.get("display_name") or m["model_id"])
        for m in catalog.get("models", [])
        if m.get("harness") == harness and m.get("kind") != "provider_source"
    ]


def invalidate_cache() -> None:
    return None
