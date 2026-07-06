# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""One-shot ClickHouse telemetry rename: ide -> harness."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "observal-server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))


async def main() -> None:
    from services.clickhouse.schema import _migrate_ide_to_harness

    await _migrate_ide_to_harness()


if __name__ == "__main__":
    asyncio.run(main())
