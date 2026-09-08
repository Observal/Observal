# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from observal_cli.discovery.models import (
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoveryScope,
    ProviderKind,
    ReasonCode,
    RegistrationStatus,
    SupportStatus,
)
from observal_cli.discovery.normalize import build_candidates
from observal_cli.harness import DiscoveredHook, DiscoveredSkill

if TYPE_CHECKING:
    from pathlib import Path


def _hook(event: str, handler_type: str, handler_config: dict) -> DiscoveryCandidate:
    evidence = DiscoveryEvidence(
        component=DiscoveredHook("audit", event, handler_type, handler_config, "Audit", "test"),
        provider=ProviderKind.HARNESS,
        scope=DiscoveryScope.PROJECT,
        harness="kiro",
        display_path="<project>/.kiro/hooks/audit.json",
    )
    return build_candidates([evidence])[0]


@pytest.mark.parametrize(
    ("event", "handler_type", "handler_config", "missing_field"),
    [
        ("UnknownEvent", "command", {"command": "audit"}, "event"),
        ("PreToolUse", "extension", {"extension": "audit.ts"}, "handler_type"),
        ("PreToolUse", "command", {"command": "/opt/local/audit"}, "handler_config.command"),
        ("PreToolUse", "command", {"command": "audit --unsafe"}, "handler_config.command"),
    ],
)
def test_invalid_hook_sources_are_classified_before_registration(
    event: str, handler_type: str, handler_config: dict, missing_field: str
) -> None:
    candidate = _hook(event, handler_type, handler_config)

    assert candidate.support_status is SupportStatus.UNSUPPORTED
    assert candidate.registration_status is RegistrationStatus.INCOMPLETE
    assert candidate.reason_codes == [ReasonCode.UNSUPPORTED_LAUNCH]
    assert candidate.missing_fields == [missing_field]


@pytest.mark.parametrize("source_kind", ["missing", "empty", "oversized"])
def test_nonportable_skill_content_is_classified_before_registration(tmp_path: Path, source_kind: str) -> None:
    source = tmp_path / source_kind / "SKILL.md"
    if source_kind != "missing":
        source.parent.mkdir(parents=True)
        source.write_text("" if source_kind == "empty" else "x" * (1024 * 1024 + 1))
    evidence = DiscoveryEvidence(
        component=DiscoveredSkill("helper", "Helps", "test", "general"),
        provider=ProviderKind.HARNESS,
        scope=DiscoveryScope.PROJECT,
        harness="kiro",
        source_path=source,
        display_path="<project>/.kiro/skills/helper/SKILL.md",
    )

    candidate = build_candidates([evidence])[0]

    assert candidate.support_status is SupportStatus.SUPPORTED
    assert candidate.registration_status is RegistrationStatus.INCOMPLETE
    assert candidate.reason_codes == [ReasonCode.MISSING_REQUIRED_FIELDS]
    assert candidate.missing_fields == ["skill_md_content"]
