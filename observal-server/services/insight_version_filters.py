# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""ClickHouse filters for insights agent version compatibility."""

from __future__ import annotations

LEGACY_UNVERSIONED_AGENT_VERSION = "1.0.0"


def agent_version_filter(
    *, nullable: bool = False, column: str = "agent_version", parameter: str = "agent_version"
) -> str:
    """Return a ClickHouse predicate for version scoped insights telemetry.

    Older Observal releases ingested session telemetry without agent_version.
    Insights treated that telemetry as the first published agent version, so
    v1.0.0 reports should continue to include unversioned rows. Later versions
    still require an exact telemetry version match.
    """
    param = "{" + parameter + ":String}"
    column_expr = f"coalesce({column}, '')" if nullable else column
    return (
        f"({param} = '' OR {column_expr} = {param} "
        f"OR ({param} = '{LEGACY_UNVERSIONED_AGENT_VERSION}' AND {column_expr} = ''))"
    )
