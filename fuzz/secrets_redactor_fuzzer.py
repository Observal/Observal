#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Fuzz the server-side secrets redactor.

``services.secrets_redactor.redact_secrets`` runs on every transcript line and
every content preview before either is written to ClickHouse. It is the last
control that keeps API keys, JWTs, connection-string passwords and PEM blocks
out of stored telemetry, and it is driven entirely by regular expressions --
so it carries both a correctness risk (a missed secret is a leak) and an
availability risk (catastrophic backtracking on attacker-shaped input).

The oracle is the contract stated in the function's own docstring: redaction
is idempotent. Anything that breaks that, raises, or hangs is a finding.
"""

import sys

import _paths
import atheris

_paths.add_source_roots()

with atheris.instrument_imports():
    from services.secrets_redactor import REDACTED, redact_secrets

# Backtracking blows up far below this, so a smaller cap only costs coverage.
_MAX_INPUT_BYTES = 4096


def TestOneInput(data: bytes) -> None:  # noqa: N802 -- Atheris entry point
    if len(data) > _MAX_INPUT_BYTES:
        return

    text = data.decode("utf-8", errors="replace")
    once = redact_secrets(text)
    assert redact_secrets(once) == once, "redact_secrets is documented as idempotent"

    secret = data[:64].hex().ljust(8, "0")
    leaked = f"password={REDACTED}{secret}"
    assert secret not in redact_secrets(leaked), "a redaction marker must not hide a live password"


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
