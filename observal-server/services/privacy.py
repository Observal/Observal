# SPDX-FileCopyrightText: 2026 Nav-Prak <naveenprakaasam@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Organization ingest privacy modes (data minimization at ingest).

Secret redaction is always applied regardless of mode (see
``services.secrets_redactor``). The privacy mode only controls how much raw
payload content is retained:

- ``full``          - retain payloads (input/output/error/raw_line) + metadata/tags.
- ``redacted``      - retain metadata/tags; replace free-text payloads with short
                      redacted previews.
- ``metadata_only`` - drop free-text payloads entirely; retain metadata/tags.
- ``disabled_raw``  - drop payloads and metadata/tags; keep only metrics/identifiers.
"""

from __future__ import annotations

PRIVACY_MODE_FULL = "full"
PRIVACY_MODE_REDACTED = "redacted"
PRIVACY_MODE_METADATA_ONLY = "metadata_only"
PRIVACY_MODE_DISABLED_RAW = "disabled_raw"

PRIVACY_MODES = (
    PRIVACY_MODE_FULL,
    PRIVACY_MODE_REDACTED,
    PRIVACY_MODE_METADATA_ONLY,
    PRIVACY_MODE_DISABLED_RAW,
)

DEFAULT_PRIVACY_MODE = PRIVACY_MODE_FULL


def normalize_privacy_mode(mode: str | None) -> str:
    """Coerce an arbitrary value to a known privacy mode, defaulting to ``full``."""
    if isinstance(mode, str) and mode in PRIVACY_MODES:
        return mode
    return DEFAULT_PRIVACY_MODE
