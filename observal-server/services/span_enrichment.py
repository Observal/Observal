# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Server-side span enrichment for SDK Phase 1 causal metadata.

Pure functions. No I/O. Populates fields the caller didn't provide.
Never overwrites caller-provided values.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from services.secrets_redactor import redact_secrets
from services.tool_file_extraction import extract_files

if TYPE_CHECKING:
    from schemas.telemetry import SpanIngest

OUTPUT_EXCERPT_MAX_CHARS = 2048


def _canonical_json(text: str) -> str:
    """Canonicalize for hashing: parse if JSON, re-emit with sorted keys.

    Falls back to the raw text when parsing fails, so non-JSON outputs
    still hash deterministically.
    """
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return text
    try:
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        return text


def compute_output_excerpt(output: str) -> str:
    """First N chars of output after running it through the secrets scrubber."""
    scrubbed = redact_secrets(output)
    return scrubbed[:OUTPUT_EXCERPT_MAX_CHARS]


def compute_tool_result_hash(output: str) -> str:
    """SHA256 of canonical JSON of output (or raw text if not JSON)."""
    canonical = _canonical_json(output)
    return hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()


def hash_state_value(value) -> str:
    """SHA256 of the canonical JSON of an arbitrary state value.

    Agents and callers should use this (or a bit-for-bit equivalent) so
    server-side comparison against ``OutcomeCheck.STATE_EQUALS`` produces
    matching hashes.
    """
    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        canonical = str(value)
    return hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()


def enrich_span(span: SpanIngest) -> SpanIngest:
    """Populate server-derivable fields if absent. Caller-provided values are preserved."""
    if span.output_excerpt is None and span.output is not None:
        span.output_excerpt = compute_output_excerpt(span.output)

    if span.tool_result_hash is None and span.output is not None:
        span.tool_result_hash = compute_tool_result_hash(span.output)

    if span.files_read is None and span.files_written is None:
        reads, writes = extract_files(
            name=span.name,
            method=span.method,
            input_str=span.input,
            metadata=span.metadata,
        )
        span.files_read = reads
        span.files_written = writes

    return span
