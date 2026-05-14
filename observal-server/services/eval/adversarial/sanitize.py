# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Adversarial input sanitization.

Strips or normalizes patterns that smuggle instructions into evaluator
context: HTML/XML comments, markdown comments, unicode homoglyphs,
zero-width runs, fenced delimiter abuse. Emits CheckResults on the
side: INPUT_SANITIZED per cleaned span; INPUT_TAMPERED if a tampering
signature was detected (and recoverable evidence preserved in meta).

Sanitization runs **before** alignment / Council see the span; mutating
the trace span is the caller's responsibility — `sanitize_span()`
returns a sanitized clone without mutating the input.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from services.eval.check_result.models import (
    Category,
    CheckResult,
    CheckType,
    SpanRef,
    Status,
)
from services.eval.trace_dag.models import TraceNode

# HTML/XML/markdown comments embedding evaluator-targeted instructions
_COMMENT_RE = re.compile(
    r"(<!--.*?-->)|(\[//\]:\s*#\s*\(.*?\))|(<%--.*?--%>)",
    re.IGNORECASE | re.DOTALL,
)
_INSTRUCTION_RE = re.compile(
    r"\b(SYSTEM|INSTRUCTION|EVALUATION|JUDGE|SCORE|RATING|OVERRIDE|IGNORE\s+PREVIOUS)\b",
    re.IGNORECASE,
)
# 6+ consecutive zero-width chars = smuggled payload
_ZERO_WIDTH_RE = re.compile(r"[​‌‍﻿⁠]{4,}")

# Latin homoglyph map — Cyrillic / Greek lookalikes.
_HOMOGLYPHS = {
    # Cyrillic -> Latin
    "\u0430": "a",
    "\u0410": "A",
    "\u0435": "e",
    "\u0415": "E",
    "\u043e": "o",
    "\u041e": "O",
    "\u0440": "p",
    "\u0420": "P",
    "\u0441": "c",
    "\u0421": "C",
    "\u0443": "y",
    "\u0423": "Y",
    "\u0445": "x",
    "\u0425": "X",
    "\u0456": "i",
    "\u0406": "I",
    # Greek -> Latin
    "\u03bf": "o",
    "\u039f": "O",
    "\u03b1": "a",
    "\u03b5": "e",
}


@dataclass(frozen=True)
class SanitizeResult:
    sanitized: str
    tampering_signatures: list[str]


def _strip_comments(text: str) -> tuple[str, list[str]]:
    sigs: list[str] = []
    out_parts: list[str] = []
    last = 0
    for m in _COMMENT_RE.finditer(text):
        body = m.group(0)
        if _INSTRUCTION_RE.search(body):
            sigs.append("hidden_comment_instruction")
        out_parts.append(text[last : m.start()])
        last = m.end()
    out_parts.append(text[last:])
    return "".join(out_parts), sigs


def _normalize_homoglyphs(text: str) -> tuple[str, list[str]]:
    sigs: list[str] = []
    chars: list[str] = []
    for ch in text:
        if ch in _HOMOGLYPHS:
            sigs.append("homoglyph")
            chars.append(_HOMOGLYPHS[ch])
        else:
            chars.append(ch)
    nfkc = unicodedata.normalize("NFKC", "".join(chars))
    if nfkc != "".join(chars):
        sigs.append("non_nfkc_form")
    return nfkc, sigs


def _strip_zero_width(text: str) -> tuple[str, list[str]]:
    sigs: list[str] = []
    if _ZERO_WIDTH_RE.search(text):
        sigs.append("zero_width_run")
    return _ZERO_WIDTH_RE.sub("", text), sigs


def sanitize_text(text: str) -> SanitizeResult:
    sigs: list[str] = []
    cleaned, s1 = _strip_comments(text)
    sigs.extend(s1)
    cleaned, s2 = _normalize_homoglyphs(cleaned)
    sigs.extend(s2)
    cleaned, s3 = _strip_zero_width(cleaned)
    sigs.extend(s3)
    # de-dup but preserve order
    seen: set[str] = set()
    unique_sigs = [s for s in sigs if not (s in seen or seen.add(s))]
    return SanitizeResult(sanitized=cleaned, tampering_signatures=unique_sigs)


def sanitize_span(node: TraceNode) -> tuple[TraceNode, CheckResult]:
    """Return a sanitized copy of `node` plus a CheckResult.

    INPUT_SANITIZED on clean spans; INPUT_TAMPERED when signatures fire.
    Recoverable evidence — the original input/output and signature list
    — is preserved in `meta`.
    """
    src_input = node.input or ""
    src_output = node.output or ""
    res_in = sanitize_text(src_input)
    res_out = sanitize_text(src_output)
    sigs = list(dict.fromkeys(res_in.tampering_signatures + res_out.tampering_signatures))

    # construct a sanitized clone — frozen dataclass; use __dict__ copy via replace pattern
    cleaned = TraceNode(
        span_id=node.span_id,
        trace_id=node.trace_id,
        parent_span_id=node.parent_span_id,
        name=node.name,
        method=node.method,
        type=node.type,
        start_time_ms=node.start_time_ms,
        end_time_ms=node.end_time_ms,
        input=res_in.sanitized if node.input is not None else None,
        output=res_out.sanitized if node.output is not None else None,
        output_excerpt=node.output_excerpt,
        tool_result_hash=node.tool_result_hash,
        files_read=node.files_read,
        files_written=node.files_written,
        intent_label=node.intent_label,
        references=node.references,
        status=node.status,
        metadata=dict(node.metadata),
    )

    if sigs:
        result = CheckResult(
            check_type=CheckType.INPUT_TAMPERED,
            status=Status.WARN,
            weight=1.0,
            points_earned=0.0,
            points_possible=1.0,
            evidence=[SpanRef(span_id=node.span_id, trace_id=node.trace_id)],
            category=Category.ADVERSARIAL,
            meta={
                "signatures": sigs,
                "original_input": src_input[:1024] if node.input is not None else None,
                "original_output": src_output[:1024] if node.output is not None else None,
            },
        )
    else:
        result = CheckResult(
            check_type=CheckType.INPUT_SANITIZED,
            status=Status.PASS,
            weight=1.0,
            points_earned=1.0,
            points_possible=1.0,
            evidence=[SpanRef(span_id=node.span_id, trace_id=node.trace_id)],
            category=Category.ADVERSARIAL,
            meta={},
        )
    return cleaned, result
