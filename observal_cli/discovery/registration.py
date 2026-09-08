# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Interactive, fail-closed registration of discovered component drafts."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import click
import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client
from observal_cli.agent_drafts import AgentDefinitionError, create_agent_draft
from observal_cli.component_drafts import (
    DraftPayloadError,
    create_hook_draft,
    create_mcp_draft,
    create_skill_draft,
)
from observal_cli.discovery.models import (
    ComponentType,
    DiscoveryCandidate,
    ReasonCode,
    RegistrationStatus,
    RegistryMatch,
    RegistryStatus,
    SupportStatus,
    TrackingStatus,
)
from observal_cli.discovery.readiness import RegistrationPayloadError, build_discovery_draft_payload
from observal_cli.discovery.redact import redact_text, sanitize_diagnostic_message
from observal_cli.discovery.registry import classify_registry_candidates
from observal_cli.errors import CliError
from observal_cli.render import console, esc
from observal_shared.namespace_rules import is_valid_namespace
from observal_shared.registry_slug import slugify

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_RECONCILIATION_ATTEMPTS = 3
_RECONCILIATION_DELAY_SECONDS = 0.1


class RegistrationResultStatus(StrEnum):
    CREATED = "created"
    EXISTING = "existing"
    DECLINED = "declined"
    SKIPPED = "skipped"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class RegistrationResult:
    candidate: DiscoveryCandidate
    status: RegistrationResultStatus
    target: str | None
    message: str

    @property
    def failed(self) -> bool:
        return self.status in {RegistrationResultStatus.FAILED, RegistrationResultStatus.UNCERTAIN}


def _create_draft(candidate: DiscoveryCandidate, payload: Mapping[str, Any]) -> dict:
    if candidate.component_type is ComponentType.AGENT:
        return create_agent_draft(payload)
    if candidate.component_type is ComponentType.MCP:
        return create_mcp_draft(payload)
    if candidate.component_type is ComponentType.SKILL:
        return create_skill_draft(payload)
    if candidate.component_type is ComponentType.HOOK:
        return create_hook_draft(payload)
    raise RegistrationPayloadError("Candidate type is not registrable")


def _target(candidate: DiscoveryCandidate, namespace: str) -> str:
    try:
        return f"{namespace}/{slugify(candidate.local_name)}"
    except ValueError as error:
        raise RegistrationPayloadError("Candidate has no valid canonical Registry target") from error


def _response_match(candidate: DiscoveryCandidate, response: object, target: str) -> RegistryMatch | None:
    if not isinstance(response, dict):
        return None
    item_id = response.get("id")
    status = response.get("status")
    qualified_name = response.get("qualified_name")
    if not all(isinstance(value, str) and value.strip() for value in (item_id, status, qualified_name)):
        return None
    if qualified_name != target:
        return None
    return RegistryMatch(
        id=item_id,
        qualified_name=target,
        status=status,
        component_type=candidate.component_type,
        owned=True,
        version=response.get("version") if isinstance(response.get("version"), str) else None,
    )


def _apply_created(candidate: DiscoveryCandidate, match: RegistryMatch) -> None:
    candidate.registry_match = match
    candidate.registry_status = RegistryStatus.OWNED_EXISTING
    candidate.registration_status = RegistrationStatus.ALREADY_EXISTS
    candidate.reason_codes = [
        reason
        for reason in candidate.reason_codes
        if reason
        not in {
            ReasonCode.NO_EXACT_REGISTRY_MATCH,
            ReasonCode.REGISTRY_EXACT_MATCH,
            ReasonCode.REGISTRY_UNAVAILABLE,
            ReasonCode.REGISTRY_LOOKUP_INCOMPLETE,
        }
    ]
    if ReasonCode.REGISTRY_OWNED_EXISTING not in candidate.reason_codes:
        candidate.reason_codes.append(ReasonCode.REGISTRY_OWNED_EXISTING)


def _reconcile(
    candidate: DiscoveryCandidate,
    *,
    configuration: dict[str, Any] | None,
    attempts: int = _RECONCILIATION_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> RegistryMatch | None:
    for attempt in range(attempts):
        classify_registry_candidates([candidate], configuration=configuration)
        if candidate.registry_status in {RegistryStatus.OWNED_EXISTING, RegistryStatus.EXACT_MATCH}:
            return candidate.registry_match
        if attempt + 1 < attempts:
            sleep(_RECONCILIATION_DELAY_SECONDS)
    return None


def _identity() -> str:
    identity = client.get(
        "/api/v1/auth/whoami",
        operation="Resolve Registry owner identity",
        resource="authenticated user",
    )
    username = identity.get("username") if isinstance(identity, dict) else None
    if not isinstance(username, str) or not is_valid_namespace(username):
        raise RegistrationPayloadError("Authenticated Registry owner namespace is unavailable")
    return username.strip().lower()


def _show_candidate(candidate: DiscoveryCandidate, target: str) -> None:
    rprint(f"\n[bold]Discovered {candidate.component_type.value}:[/bold] {esc(candidate.local_name)}")
    rprint(f"Proposed Registry target: [cyan]{esc(target)}[/cyan]")
    for evidence in candidate.evidence:
        source = evidence.display_path or evidence.provider.value
        harness = f" ({evidence.harness})" if evidence.harness else ""
        rprint(f"  [dim]• {evidence.provider.value}{esc(harness)}: {esc(source)}[/dim]")
    rprint("[dim]The draft is portable, but may require edits before it can be submitted for review.[/dim]")


def _show_summary(candidate: DiscoveryCandidate, target: str, payload: Mapping[str, Any]) -> None:
    table = Table(title="Draft Summary", show_lines=False)
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Type", candidate.component_type.value)
    table.add_row("Target", esc(target))
    table.add_row("Version", esc(str(payload.get("version", "0.1.0"))))
    table.add_row("Harnesses", esc(", ".join(payload.get("supported_harnesses", [])) or "none"))
    table.add_row("Description", esc(redact_text(str(payload.get("description", "")))[:160] or "-"))
    console.print(table)


def _result_for_existing(candidate: DiscoveryCandidate, target: str) -> RegistrationResult:
    return RegistrationResult(candidate, RegistrationResultStatus.EXISTING, target, "Canonical Registry target exists")


def _is_promptable(candidate: DiscoveryCandidate) -> bool:
    return (
        candidate.registration_status is RegistrationStatus.ELIGIBLE
        and candidate.registry_status is RegistryStatus.NO_EXACT_MATCH
        and candidate.support_status is SupportStatus.SUPPORTED
        and candidate.tracking_status is TrackingStatus.NOT_TRACKED
    )


def register_discovery_candidates(
    candidates: list[DiscoveryCandidate],
    *,
    output: str = "table",
    stdin_is_tty: bool | None = None,
    configuration: dict[str, Any] | None = None,
    confirm: Callable[..., bool] | None = None,
) -> list[RegistrationResult]:
    """Interactively offer safe draft creation for independently eligible candidates."""

    interactive = sys.stdin.isatty() if stdin_is_tty is None else stdin_is_tty
    confirmation = confirm or typer.confirm
    if output == "json" or not interactive:
        return [
            RegistrationResult(candidate, RegistrationResultStatus.SKIPPED, None, "Interactive registration disabled")
            for candidate in candidates
            if _is_promptable(candidate)
        ]

    promptable = [candidate for candidate in candidates if _is_promptable(candidate)]
    results: list[RegistrationResult] = []
    if not promptable:
        for candidate in candidates:
            if candidate.registration_status is RegistrationStatus.ALREADY_EXISTS:
                target = candidate.registry_match.qualified_name if candidate.registry_match else None
                results.append(_result_for_existing(candidate, target or "unknown"))
            else:
                results.append(
                    RegistrationResult(candidate, RegistrationResultStatus.SKIPPED, None, "Candidate is not eligible")
                )
        return results
    try:
        namespace = _identity()
    except (CliError, RegistrationPayloadError) as error:
        message = error.message if isinstance(error, CliError) else str(error)
        for candidate in candidates:
            if candidate.registration_status is RegistrationStatus.ALREADY_EXISTS:
                target = candidate.registry_match.qualified_name if candidate.registry_match else None
                results.append(_result_for_existing(candidate, target or "unknown"))
            elif _is_promptable(candidate):
                results.append(RegistrationResult(candidate, RegistrationResultStatus.FAILED, None, message))
            else:
                results.append(
                    RegistrationResult(candidate, RegistrationResultStatus.SKIPPED, None, "Candidate is not eligible")
                )
        return results

    for candidate in candidates:
        if candidate.registration_status is RegistrationStatus.ALREADY_EXISTS:
            target = candidate.registry_match.qualified_name if candidate.registry_match else None
            if target is None:
                try:
                    target = _target(candidate, namespace)
                except RegistrationPayloadError as error:
                    results.append(RegistrationResult(candidate, RegistrationResultStatus.SKIPPED, None, str(error)))
                    continue
            results.append(_result_for_existing(candidate, target))
            continue
        if not _is_promptable(candidate):
            results.append(
                RegistrationResult(candidate, RegistrationResultStatus.SKIPPED, None, "Candidate is not eligible")
            )
            continue
        try:
            target = _target(candidate, namespace)
        except RegistrationPayloadError as error:
            results.append(RegistrationResult(candidate, RegistrationResultStatus.SKIPPED, None, str(error)))
            continue

        # Refresh owned and exact state immediately before any user decision.
        classify_registry_candidates([candidate], configuration=configuration)
        if candidate.registration_status is RegistrationStatus.ALREADY_EXISTS:
            results.append(_result_for_existing(candidate, target))
            continue
        if not _is_promptable(candidate):
            results.append(
                RegistrationResult(
                    candidate, RegistrationResultStatus.FAILED, target, "Registry preflight was unavailable"
                )
            )
            continue
        try:
            payload = build_discovery_draft_payload(candidate, owner=namespace)
        except (AgentDefinitionError, DraftPayloadError, RegistrationPayloadError, OSError) as error:
            candidate.registration_status = RegistrationStatus.INCOMPLETE
            candidate.support_status = SupportStatus.UNSUPPORTED
            if ReasonCode.MISSING_REQUIRED_FIELDS not in candidate.reason_codes:
                candidate.reason_codes.append(ReasonCode.MISSING_REQUIRED_FIELDS)
            results.append(RegistrationResult(candidate, RegistrationResultStatus.SKIPPED, target, str(error)))
            continue

        _show_candidate(candidate, target)
        try:
            if not confirmation("Create this Registry draft?", default=False):
                results.append(RegistrationResult(candidate, RegistrationResultStatus.DECLINED, target, "Declined"))
                continue
            if not confirmation(
                "I confirm that I own or am authorized to register this component and its included content",
                default=False,
            ):
                results.append(
                    RegistrationResult(candidate, RegistrationResultStatus.DECLINED, target, "Ownership not confirmed")
                )
                continue
            _show_summary(candidate, target, payload)
            if not confirmation("Create the draft with this sanitized payload?", default=False):
                results.append(
                    RegistrationResult(
                        candidate, RegistrationResultStatus.DECLINED, target, "Final confirmation declined"
                    )
                )
                continue
        except (click.Abort, EOFError, KeyboardInterrupt):
            results.append(RegistrationResult(candidate, RegistrationResultStatus.DECLINED, target, "Cancelled"))
            continue

        try:
            mutation = client.run_mutation_once(
                lambda candidate=candidate, payload=payload: _create_draft(candidate, payload)
            )
        except (CliError, AgentDefinitionError, DraftPayloadError, RegistrationPayloadError) as error:
            message = error.message if isinstance(error, CliError) else str(error)
            results.append(RegistrationResult(candidate, RegistrationResultStatus.FAILED, target, message))
            continue

        if mutation.status is client.MutationStatus.SUCCESS:
            match = _response_match(candidate, mutation.data, target)
            if match is not None:
                _apply_created(candidate, match)
                results.append(RegistrationResult(candidate, RegistrationResultStatus.CREATED, target, "Draft created"))
                continue
            match = _reconcile(candidate, configuration=configuration)
            if match is not None:
                results.append(_result_for_existing(candidate, target))
            else:
                results.append(
                    RegistrationResult(
                        candidate,
                        RegistrationResultStatus.UNCERTAIN,
                        target,
                        "Draft response could not be reconciled; run discovery again before retrying",
                    )
                )
            continue

        match = _reconcile(candidate, configuration=configuration)
        if match is not None:
            results.append(_result_for_existing(candidate, target))
        elif mutation.status is client.MutationStatus.CONFLICT:
            results.append(
                RegistrationResult(
                    candidate, RegistrationResultStatus.FAILED, target, "Conflict could not be reconciled"
                )
            )
        else:
            results.append(
                RegistrationResult(
                    candidate,
                    RegistrationResultStatus.UNCERTAIN,
                    target,
                    "Draft mutation state is unknown; run discovery again before retrying",
                )
            )
    return results


def render_registration_results(results: list[RegistrationResult]) -> None:
    if not results:
        return
    table = Table(title="Discovery Registration Results", show_lines=False)
    table.add_column("Type", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Target")
    table.add_column("Result")
    table.add_column("Details", style="dim")
    for result in results:
        component_type = result.candidate.component_type.value if result.candidate.component_type else "unknown"
        table.add_row(
            component_type,
            esc(result.candidate.local_name),
            esc(result.target or "-"),
            result.status.value,
            esc(sanitize_diagnostic_message(result.message)),
        )
    console.print(table)
    rprint()
