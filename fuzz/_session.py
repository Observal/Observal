# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Shared oracle for the session-transcript fuzz targets.

Both session targets drive the same trust boundary and differ only in how
they produce input, so the pipeline replay and its invariants live here.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import _paths

_paths.add_source_roots()

if TYPE_CHECKING:
    from collections.abc import Iterable

from observal_shared.harness_registry import HARNESS_REGISTRY  # noqa: E402
from services.session_parsers import parse_raw_events  # noqa: E402
from services.session_parsers.ingest_classify import extract_timestamp, get_classifier  # noqa: E402

# Sorted so a given input always selects the same harness across runs.
HARNESSES = tuple(sorted(HARNESS_REGISTRY))

# Every event handed to the trace viewer by api/routes/sessions.py carries these.
_FRONTEND_EVENT_KEYS = frozenset({"timestamp", "event_name", "body", "attributes", "service_name"})

# Fixed row metadata so all input entropy lands in the transcript line itself
# rather than in columns the parsers only echo back.
_ROW_TIMESTAMP = "2026-01-01 00:00:00.000"
_ROW_INGESTED_AT = "2026-01-01 00:00:01.000"


def _stored_row(harness: str, raw_line: str, event_type: str) -> dict:
    """Build the subset of a ``session_events`` row that the read path consumes."""
    return {
        "harness": harness,
        "raw_line": raw_line,
        "event_type": event_type,
        "timestamp": _ROW_TIMESTAMP,
        "ingested_at": _ROW_INGESTED_AT,
        "content_preview": "",
        "content_length": len(raw_line),
        "tool_name": None,
        "tool_id": None,
        "uuid": None,
        "parent_uuid": None,
        "credits": None,
    }


def replay(harness: str, raw_lines: Iterable[str]) -> None:
    """Run one transcript through ingest classification and the read-path parser.

    Mirrors the per-line loop in ``services.session_ingest`` and then feeds the
    stored rows to ``parse_raw_events``, asserting the contract both halves owe
    their callers. Returns early when the input would be rejected before it
    could reach storage.
    """
    classify_fn, preview_fn, tool_info_fn = get_classifier(harness)
    rows: list[dict] = []

    for raw_line in raw_lines:
        try:
            decoded = json.loads(raw_line)
        except RecursionError:
            # Ingestion decodes with orjson, which rejects deeply nested documents
            # outright where CPython's json module recurses instead. Drop the input
            # rather than report a limitation of the stdlib decoder.
            return
        except ValueError:
            decoded = None

        # Classification runs outside the decoder's except clause so that a
        # ValueError raised by a classifier is a finding, not a parse error.
        parsed: dict = {}
        event_type = "_parse_error"
        rendered = False
        if isinstance(decoded, dict):
            parsed = decoded
            event_type = classify_fn(parsed)
            assert event_type is None or isinstance(event_type, str), (
                f"{harness} classifier returned {type(event_type).__name__}"
            )
            rendered = event_type is not None
            if event_type is None:
                event_type = "_ignored"

        if parsed:
            extract_timestamp(harness, parsed)
        if rendered:
            preview_fn(parsed, event_type)
            tool_info_fn(parsed)

        # Lines that failed to decode are stored too, so the read path sees them.
        rows.append(_stored_row(harness, raw_line, event_type))

    for event in parse_raw_events(rows):
        assert event.keys() >= _FRONTEND_EVENT_KEYS, f"{harness} event is missing {_FRONTEND_EVENT_KEYS - event.keys()}"
        assert isinstance(event["attributes"], dict), f"{harness} event attributes must be a mapping"
