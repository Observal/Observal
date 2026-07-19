# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnumuthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from loguru import logger as optic

from services.harness import ensure_loaded, get_adapter


def generate_hook_telemetry_config(
    hook_listing, harness: str, server_url: str = "http://localhost:8000", platform: str = ""
) -> dict:
    """Generate telemetry hook configuration through a harness adapter."""
    optic.debug("generating hook config for {} (event={})", harness, hook_listing.event)
    ensure_loaded()
    adapter = get_adapter(harness)
    if adapter is None:
        raise ValueError(f"No adapter registered for harness: {harness!r}")
    return adapter.format_hook_telemetry(hook_listing, server_url, platform)
