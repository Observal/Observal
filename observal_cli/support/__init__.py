# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: Apache-2.0

# observal_cli/support - diagnostic support bundle helpers

from dataclasses import dataclass


@dataclass
class CollectorResult:
    """Result from a single diagnostic collector."""

    name: str  # e.g. "versions", "health_postgres"
    ok: bool
    duration_ms: int
    data: dict | list | str | None
    error: str | None = None

    @property
    def target_path(self) -> str:
        """Relative path in the archive, e.g. 'versions/app.json'."""
        _path_map: dict[str, str] = {
            "versions": "versions/app.json",
            "health": "health/health.json",
            "config": "config/config.json",
            "aggregates": "aggregates/aggregates.json",
            "errors": "errors/recent_errors.json",
            "logs": "logs/recent.ndjson",
            "config_allowlisted": "config/config.json",
            "system_info": "system/system.json",
        }
        return _path_map.get(self.name, f"{self.name}.json")
