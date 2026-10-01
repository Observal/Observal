# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Harness-neutral skill evidence facts, dispatched by verified harness support.

A harness opts in through ``HARNESS_REGISTRY[...]["skill_evidence_extractor"]``.
An unsupported harness is not a supported session with no skill evidence.

Evidence kinds, none of which shows that a skill achieved anything:

* ``available``: the harness advertised the installed skill to the model.
* ``loaded``: the model read the installed skill's instructions.
* ``invoked``: the user explicitly invoked the skill.

Facts identify a skill by its install ``scope`` and ``alias`` (the directory
Observal installed it into), never by the model-visible name, and carry no
absolute paths, transcript text, or skill content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from observal_shared.harness_registry import HARNESS_REGISTRY

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

EvidenceKind = Literal["available", "loaded", "invoked"]


@dataclass(frozen=True)
class SkillEvidence:
    kind: EvidenceKind
    scope: Literal["user", "project"]
    alias: str
    source_line_offset: int
    source_block_key: str
    event_time: datetime | None
    # Only for ``loaded``: whether the read itself returned an error.
    result_state: Literal["unknown", "success", "error"] = "unknown"


@dataclass(frozen=True)
class SkillEvidenceExtraction:
    status: Literal["supported", "unsupported"]
    evidence: tuple[SkillEvidence, ...]
    malformed_source_records: int = 0


class SkillEvidenceExtractor(Protocol):
    def extract(self, rows: Sequence[Mapping[str, object]]) -> SkillEvidenceExtraction: ...


def _extractors() -> dict[str, SkillEvidenceExtractor]:
    from .pi_skill_evidence import PiSkillEvidenceExtractor

    return {"pi": PiSkillEvidenceExtractor()}


def extract_skill_evidence(harness: str, rows: Sequence[Mapping[str, object]]) -> SkillEvidenceExtraction:
    """Resolve a registered harness's opt-in extractor; never guess a transcript format."""
    extractor_id = HARNESS_REGISTRY[harness].get("skill_evidence_extractor")  # unknown harness: KeyError
    if extractor_id is None:
        return SkillEvidenceExtraction(status="unsupported", evidence=())
    return _extractors()[extractor_id].extract(rows)  # unknown extractor: KeyError
