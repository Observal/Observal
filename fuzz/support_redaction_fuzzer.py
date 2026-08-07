#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Fuzz the support-bundle redaction chokepoint.

``observal support bundle`` collects configuration, health probes and recent
log lines into an archive that operators hand to third parties for diagnosis.
``observal_cli.support.redaction`` is the single point every value passes
through on the way in, so a miss here leaks credentials outside the
deployment. It is a separate implementation from the server-side ingest
redactor: different patterns, plus a Shannon-entropy rule over tokenised
input.

The oracle is the contract the module's property tests already assert:
redaction is idempotent, so a second pass must be a no-op.
"""

import sys

import _paths
import atheris

_paths.add_source_roots()

with atheris.instrument_imports():
    from observal_cli.support.redaction import REDACTED, redact_string

# The entropy rule is quadratic in token count; cap input so slow cases are
# reported as bugs rather than as libFuzzer timeouts.
_MAX_INPUT_BYTES = 4096


def TestOneInput(data: bytes) -> None:  # noqa: N802 -- Atheris entry point
    if len(data) > _MAX_INPUT_BYTES:
        return

    text = data.decode("utf-8", errors="replace")
    once, _ = redact_string(text)
    twice, _ = redact_string(once)
    assert twice == once, "redact_string must be idempotent"

    secret = data[:64].hex().ljust(8, "0")
    leaked = f"https://{REDACTED}{secret}@host"
    cleaned, _ = redact_string(leaked)
    assert secret not in cleaned, "a redaction marker must not hide live URL credentials"


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
