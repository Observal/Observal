#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Fuzz the harness session-transcript pipeline with arbitrary JSONL.

Session transcripts are the largest untrusted input Observal accepts. A coding
harness writes JSONL to disk, a session-push hook (or ``observal reconcile``)
uploads the raw lines to ``POST /api/v1/ingest/session``, and the server
classifies each line before storing it verbatim in ClickHouse. The stored line
is decoded again on the read path whenever the trace viewer opens a session.

``_session.replay`` drives both halves in-process. Nothing here touches the
network, a database, credentials or the clock.

Input layout: the first byte selects the harness, everything after it is the
transcript. Seed corpus files therefore start with a single selector character
and are otherwise plain JSONL.
"""

import sys

import atheris

with atheris.instrument_imports():
    import _session

# Transcripts longer than this cost execution time without reaching new parser
# states, and slow inputs are reported as timeouts rather than as bugs.
_MAX_INPUT_BYTES = 8192


def TestOneInput(data: bytes) -> None:  # noqa: N802 -- Atheris entry point
    if not data or len(data) > _MAX_INPUT_BYTES:
        return

    fdp = atheris.FuzzedDataProvider(data)
    harness = _session.HARNESSES[fdp.ConsumeBytes(1)[0] % len(_session.HARNESSES)]
    transcript = fdp.ConsumeBytes(len(data)).decode("utf-8", errors="replace")

    _session.replay(harness, transcript.split("\n"))


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
