# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from unittest.mock import Mock

import pytest

from observal_cli import client, lockfile
from observal_cli.discovery import registration
from observal_cli.discovery.models import (
    ComponentType,
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoveryScope,
    LaunchKind,
    ProviderKind,
    RegistrationStatus,
    RegistryMatch,
    RegistryStatus,
    SanitizedLaunch,
    SupportStatus,
    TrackingStatus,
)
from observal_cli.discovery.readiness import RegistrationPayloadError, build_discovery_draft_payload
from observal_cli.discovery.registration import RegistrationResultStatus, register_discovery_candidates
from observal_cli.errors import CliError, ErrorCategory
from observal_cli.harness import DiscoveredAgent, DiscoveredHook, DiscoveredMcp, DiscoveredSkill


def _candidate(name: str = "Review Helper") -> DiscoveryCandidate:
    return DiscoveryCandidate(
        component_type=ComponentType.AGENT,
        local_name=name,
        correlation_identity=None,
        launch_fingerprint=None,
        evidence=[
            DiscoveryEvidence(
                component=DiscoveredAgent(name, "Reviews changes", "claude-sonnet-4", "Review carefully.", "AGENT.md"),
                provider=ProviderKind.HARNESS,
                scope=DiscoveryScope.PROJECT,
                harness="kiro",
                display_path="<project>/AGENT.md",
            )
        ],
        registry_status=RegistryStatus.NO_EXACT_MATCH,
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
    )


def _match(candidate: DiscoveryCandidate, *, name: str | None = None) -> None:
    slug = (name or candidate.local_name).lower().replace(" ", "-")
    candidate.registry_status = RegistryStatus.OWNED_EXISTING
    candidate.registration_status = RegistrationStatus.ALREADY_EXISTS
    candidate.registry_match = RegistryMatch(
        id=f"id-{slug}",
        qualified_name=f"alice/{slug}",
        status="draft",
        component_type=candidate.component_type,
        owned=True,
    )


def _identity(monkeypatch) -> None:
    monkeypatch.setattr(registration.client, "get", Mock(return_value={"username": "alice"}))


def test_json_and_non_tty_registration_never_prompt_or_mutate(monkeypatch) -> None:
    confirm = Mock(side_effect=AssertionError("must not prompt"))
    post = Mock(side_effect=AssertionError("must not mutate"))
    monkeypatch.setattr(registration.client, "post", post)

    json_results = register_discovery_candidates([_candidate()], output="json", stdin_is_tty=True, confirm=confirm)
    tty_results = register_discovery_candidates([_candidate()], output="table", stdin_is_tty=False, confirm=confirm)

    assert json_results[0].status is RegistrationResultStatus.SKIPPED
    assert tty_results[0].status is RegistrationResultStatus.SKIPPED
    confirm.assert_not_called()
    post.assert_not_called()


@pytest.mark.parametrize("tracking_status", [TrackingStatus.TRACKED, TrackingStatus.AMBIGUOUS])
def test_non_untracked_candidate_never_prompts_or_invokes_mutation(monkeypatch, tracking_status) -> None:
    candidate = _candidate()
    candidate.tracking_status = tracking_status
    identity = Mock(side_effect=AssertionError("non-untracked candidate must not authenticate for mutation"))
    confirm = Mock(side_effect=AssertionError("non-untracked candidate must not prompt"))
    mutation = Mock(side_effect=AssertionError("non-untracked candidate must not invoke mutation"))
    post = Mock(side_effect=AssertionError("non-untracked candidate must not post"))
    monkeypatch.setattr(registration.client, "get", identity)
    monkeypatch.setattr(registration.client, "run_mutation_once", mutation)
    monkeypatch.setattr(registration.client, "post", post)

    results = register_discovery_candidates([candidate], stdin_is_tty=True, confirm=confirm)

    assert results[0].status is RegistrationResultStatus.SKIPPED
    identity.assert_not_called()
    confirm.assert_not_called()
    mutation.assert_not_called()
    post.assert_not_called()


def test_invalid_target_is_skipped_without_aborting_later_candidates(monkeypatch) -> None:
    invalid = _candidate("!!!")
    valid = _candidate("Valid Agent")
    _identity(monkeypatch)
    monkeypatch.setattr(registration, "classify_registry_candidates", Mock(return_value=[]))
    post = Mock(side_effect=AssertionError("declined candidate must not mutate"))
    monkeypatch.setattr(registration.client, "post", post)
    confirm = Mock(return_value=False)

    results = register_discovery_candidates([invalid, valid], stdin_is_tty=True, confirm=confirm, configuration={})

    assert [result.status for result in results] == [
        RegistrationResultStatus.SKIPPED,
        RegistrationResultStatus.DECLINED,
    ]
    assert "canonical Registry target" in results[0].message
    confirm.assert_called_once_with("Create this Registry draft?", default=False)
    post.assert_not_called()


def test_decline_and_cancel_never_mutate(monkeypatch) -> None:
    _identity(monkeypatch)
    monkeypatch.setattr(registration, "classify_registry_candidates", Mock(return_value=[]))
    post = Mock(side_effect=AssertionError("must not mutate"))
    monkeypatch.setattr(registration.client, "post", post)

    declined = register_discovery_candidates(
        [_candidate()], stdin_is_tty=True, confirm=Mock(return_value=False), configuration={}
    )
    cancelled = register_discovery_candidates(
        [_candidate("Other Agent")],
        stdin_is_tty=True,
        confirm=Mock(side_effect=KeyboardInterrupt),
        configuration={},
    )

    assert declined[0].status is RegistrationResultStatus.DECLINED
    assert cancelled[0].status is RegistrationResultStatus.DECLINED
    post.assert_not_called()


def test_successful_registration_posts_once_updates_memory_and_never_writes_lockfile(monkeypatch) -> None:
    candidate = _candidate()
    _identity(monkeypatch)
    monkeypatch.setattr(registration, "classify_registry_candidates", Mock(return_value=[]))
    post = Mock(
        return_value={
            "id": "agent-1",
            "qualified_name": "alice/review-helper",
            "status": "draft",
            "version": "0.1.0",
        }
    )
    monkeypatch.setattr(registration.client, "post", post)
    write_lockfile = Mock(side_effect=AssertionError("drafts must not be installed"))
    monkeypatch.setattr(lockfile, "write_lockfile", write_lockfile)

    confirm = Mock(side_effect=[True, True, True])
    results = register_discovery_candidates([candidate], stdin_is_tty=True, confirm=confirm, configuration={})

    assert results[0].status is RegistrationResultStatus.CREATED
    assert candidate.registry_status is RegistryStatus.OWNED_EXISTING
    assert candidate.registration_status is RegistrationStatus.ALREADY_EXISTS
    assert candidate.registry_match is not None
    assert candidate.registry_match.qualified_name == "alice/review-helper"
    post.assert_called_once()
    assert [item.kwargs["default"] for item in confirm.call_args_list] == [False, False, False]
    assert "own or am authorized" in confirm.call_args_list[1].args[0]
    write_lockfile.assert_not_called()


def test_ownership_or_final_confirmation_decline_never_posts(monkeypatch) -> None:
    _identity(monkeypatch)
    monkeypatch.setattr(registration, "classify_registry_candidates", Mock(return_value=[]))
    post = Mock(side_effect=AssertionError("must not mutate"))
    monkeypatch.setattr(registration.client, "post", post)

    ownership_declined = register_discovery_candidates(
        [_candidate()], stdin_is_tty=True, confirm=Mock(side_effect=[True, False]), configuration={}
    )
    final_declined = register_discovery_candidates(
        [_candidate("Other Agent")],
        stdin_is_tty=True,
        confirm=Mock(side_effect=[True, True, False]),
        configuration={},
    )

    assert ownership_declined[0].message == "Ownership not confirmed"
    assert final_declined[0].message == "Final confirmation declined"
    post.assert_not_called()


def test_preflight_existing_suppresses_prompt_and_post(monkeypatch) -> None:
    candidate = _candidate()
    _identity(monkeypatch)

    def classify(candidates, **_kwargs):
        _match(candidates[0])
        return []

    monkeypatch.setattr(registration, "classify_registry_candidates", classify)
    confirm = Mock(side_effect=AssertionError("existing targets must not prompt"))
    post = Mock(side_effect=AssertionError("existing targets must not post"))
    monkeypatch.setattr(registration.client, "post", post)

    results = register_discovery_candidates([candidate], stdin_is_tty=True, confirm=confirm, configuration={})

    assert results[0].status is RegistrationResultStatus.EXISTING
    confirm.assert_not_called()
    post.assert_not_called()


def test_repeat_registration_of_created_candidate_suppresses_second_post(monkeypatch) -> None:
    candidate = _candidate()
    _identity(monkeypatch)
    monkeypatch.setattr(registration, "classify_registry_candidates", Mock(return_value=[]))
    post = Mock(return_value={"id": "agent-1", "qualified_name": "alice/review-helper", "status": "draft"})
    monkeypatch.setattr(registration.client, "post", post)

    first = register_discovery_candidates(
        [candidate], stdin_is_tty=True, confirm=Mock(side_effect=[True, True, True]), configuration={}
    )
    second = register_discovery_candidates(
        [candidate],
        stdin_is_tty=True,
        confirm=Mock(side_effect=AssertionError("created candidate must not prompt again")),
        configuration={},
    )

    assert first[0].status is RegistrationResultStatus.CREATED
    assert second[0].status is RegistrationResultStatus.EXISTING
    post.assert_called_once()


def test_uncertain_post_reconciles_with_gets_and_never_reposts(monkeypatch) -> None:
    candidate = _candidate()
    _identity(monkeypatch)
    calls = 0

    def classify(candidates, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            _match(candidates[0])
        return []

    monkeypatch.setattr(registration, "classify_registry_candidates", classify)
    post = Mock(
        side_effect=CliError(
            ErrorCategory.UNAVAILABLE,
            "Timed out.",
            "Create agent draft",
        )
    )
    monkeypatch.setattr(registration.client, "post", post)
    monkeypatch.setattr(registration.time, "sleep", Mock())

    results = register_discovery_candidates(
        [candidate], stdin_is_tty=True, confirm=Mock(side_effect=[True, True, True]), configuration={}
    )

    assert results[0].status is RegistrationResultStatus.EXISTING
    assert calls == 3
    post.assert_called_once()


def test_http_409_race_reconciles_and_never_reposts(monkeypatch) -> None:
    candidate = _candidate()
    _identity(monkeypatch)
    calls = 0

    def classify(candidates, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            _match(candidates[0])
        return []

    monkeypatch.setattr(registration, "classify_registry_candidates", classify)
    post = Mock(
        side_effect=CliError(
            ErrorCategory.CONFLICT,
            "Already exists.",
            "Create agent draft",
            http_status=409,
        )
    )
    monkeypatch.setattr(registration.client, "post", post)

    results = register_discovery_candidates(
        [candidate], stdin_is_tty=True, confirm=Mock(side_effect=[True, True, True]), configuration={}
    )

    assert results[0].status is RegistrationResultStatus.EXISTING
    assert calls == 2
    post.assert_called_once()


def test_unreconciled_uncertain_write_reports_unknown_without_retry(monkeypatch) -> None:
    _identity(monkeypatch)
    classify = Mock(return_value=[])
    monkeypatch.setattr(registration, "classify_registry_candidates", classify)
    post = Mock(side_effect=CliError(ErrorCategory.UNAVAILABLE, "Timeout.", "Create agent draft"))
    monkeypatch.setattr(registration.client, "post", post)
    monkeypatch.setattr(registration.time, "sleep", Mock())

    results = register_discovery_candidates(
        [_candidate()], stdin_is_tty=True, confirm=Mock(side_effect=[True, True, True]), configuration={}
    )

    assert results[0].status is RegistrationResultStatus.UNCERTAIN
    assert "run discovery again" in results[0].message
    assert classify.call_count == 4
    post.assert_called_once()


def test_unreconciled_conflict_is_failed_without_retry(monkeypatch) -> None:
    _identity(monkeypatch)
    classify = Mock(return_value=[])
    monkeypatch.setattr(registration, "classify_registry_candidates", classify)
    post = Mock(side_effect=CliError(ErrorCategory.CONFLICT, "Conflict.", "Create agent draft", http_status=409))
    monkeypatch.setattr(registration.client, "post", post)
    monkeypatch.setattr(registration.time, "sleep", Mock())

    results = register_discovery_candidates(
        [_candidate()], stdin_is_tty=True, confirm=Mock(side_effect=[True, True, True]), configuration={}
    )

    assert results[0].status is RegistrationResultStatus.FAILED
    assert classify.call_count == 4  # one preflight plus three bounded reconciliation attempts
    post.assert_called_once()


def test_partial_success_is_preserved_when_later_candidate_fails(monkeypatch) -> None:
    first = _candidate()
    second = _candidate("Second Agent")
    _identity(monkeypatch)
    monkeypatch.setattr(registration, "classify_registry_candidates", Mock(return_value=[]))
    post = Mock(
        side_effect=[
            {"id": "agent-1", "qualified_name": "alice/review-helper", "status": "draft"},
            CliError(ErrorCategory.PERMISSION, "Forbidden.", "Create agent draft", http_status=403),
        ]
    )
    monkeypatch.setattr(registration.client, "post", post)

    results = register_discovery_candidates(
        [first, second],
        stdin_is_tty=True,
        confirm=Mock(side_effect=[True, True, True, True, True, True]),
        configuration={},
    )

    assert [result.status for result in results] == [
        RegistrationResultStatus.CREATED,
        RegistrationResultStatus.FAILED,
    ]
    assert first.registration_status is RegistrationStatus.ALREADY_EXISTS
    assert second.registration_status is RegistrationStatus.ELIGIBLE
    assert post.call_count == 2


def test_mcp_payload_contains_only_portable_launch_and_secret_names() -> None:
    candidate = DiscoveryCandidate(
        component_type=ComponentType.MCP,
        local_name="Filesystem MCP",
        correlation_identity="npm:@modelcontextprotocol/server-filesystem",
        launch_fingerprint="sha256:" + "a" * 64,
        evidence=[
            DiscoveryEvidence(
                component=DiscoveredMcp(
                    "Filesystem MCP", "npx", ["-y", "@modelcontextprotocol/server-filesystem"], None, "Files", "test"
                ),
                provider=ProviderKind.HARNESS,
                scope=DiscoveryScope.PROJECT,
                harness="claude-code",
                launch=SanitizedLaunch(
                    kind=LaunchKind.NPM,
                    package="@modelcontextprotocol/server-filesystem",
                    arguments=("--safe",),
                    environment_names=("API_KEY",),
                    header_names=("Authorization",),
                ),
            )
        ],
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
    )

    payload = build_discovery_draft_payload(candidate, owner="alice")

    assert payload["command"] == "npx"
    assert payload["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "--safe"]
    assert payload["environment_variables"] == [{"name": "API_KEY", "description": "", "required": True}]
    assert payload["headers"] == [{"name": "Authorization", "description": "", "required": True}]
    assert "secret" not in repr(payload).lower()


def test_skill_payload_reads_bounded_content_and_redacts_secrets(tmp_path) -> None:
    source = tmp_path / "SKILL.md"
    source.write_text("# Helper\napi_key=ghp_abcdefghijklmnopqrstuvwxyz1234567890\n")
    candidate = DiscoveryCandidate(
        component_type=ComponentType.SKILL,
        local_name="helper",
        correlation_identity=None,
        launch_fingerprint=None,
        evidence=[
            DiscoveryEvidence(
                component=DiscoveredSkill("helper", "Helps", "test"),
                provider=ProviderKind.HARNESS,
                scope=DiscoveryScope.PROJECT,
                harness="kiro",
                source_path=source,
            )
        ],
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
    )

    payload = build_discovery_draft_payload(candidate, owner="alice")

    assert payload["delivery_mode"] == "registry_direct"
    assert "ghp_" not in payload["skill_md_content"]
    assert "<secret>" in payload["skill_md_content"]


def test_discovery_dispatches_each_component_to_its_canonical_draft_service(tmp_path, monkeypatch) -> None:
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("# Helper\nDo the task.\n")
    mcp = DiscoveryCandidate(
        component_type=ComponentType.MCP,
        local_name="search-mcp",
        correlation_identity="npm:search-mcp",
        launch_fingerprint="sha256:" + "a" * 64,
        evidence=[
            DiscoveryEvidence(
                component=DiscoveredMcp("search-mcp", "npx", ["search-mcp"], None, "Search", "test"),
                provider=ProviderKind.HARNESS,
                scope=DiscoveryScope.PROJECT,
                harness="kiro",
                launch=SanitizedLaunch(kind=LaunchKind.NPM, package="search-mcp"),
            )
        ],
        registry_status=RegistryStatus.NO_EXACT_MATCH,
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
    )
    skill = DiscoveryCandidate(
        component_type=ComponentType.SKILL,
        local_name="helper-skill",
        correlation_identity=None,
        launch_fingerprint=None,
        evidence=[
            DiscoveryEvidence(
                component=DiscoveredSkill("helper-skill", "Helps", "test"),
                provider=ProviderKind.HARNESS,
                scope=DiscoveryScope.PROJECT,
                harness="kiro",
                source_path=skill_path,
            )
        ],
        registry_status=RegistryStatus.NO_EXACT_MATCH,
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
    )
    hook = DiscoveryCandidate(
        component_type=ComponentType.HOOK,
        local_name="audit-hook",
        correlation_identity=None,
        launch_fingerprint=None,
        evidence=[
            DiscoveryEvidence(
                component=DiscoveredHook(
                    "audit-hook", "PreToolUse", "command", {"command": "audit-hook", "args": []}, "Audit", "test"
                ),
                provider=ProviderKind.HARNESS,
                scope=DiscoveryScope.PROJECT,
                harness="kiro",
            )
        ],
        registry_status=RegistryStatus.NO_EXACT_MATCH,
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
    )
    _identity(monkeypatch)
    monkeypatch.setattr(registration, "classify_registry_candidates", Mock(return_value=[]))

    def post(path, _payload):
        slug = {
            "/api/v1/mcps/draft": "search-mcp",
            "/api/v1/skills/draft": "helper-skill",
            "/api/v1/hooks/draft": "audit-hook",
        }[path]
        return {"id": f"id-{slug}", "qualified_name": f"alice/{slug}", "status": "draft"}

    post_mock = Mock(side_effect=post)
    monkeypatch.setattr(registration.client, "post", post_mock)

    results = register_discovery_candidates(
        [mcp, skill, hook],
        stdin_is_tty=True,
        confirm=Mock(side_effect=[True] * 9),
        configuration={},
    )

    assert [result.status for result in results] == [RegistrationResultStatus.CREATED] * 3
    assert [item.args[0] for item in post_mock.call_args_list] == [
        "/api/v1/mcps/draft",
        "/api/v1/skills/draft",
        "/api/v1/hooks/draft",
    ]


def test_hook_with_local_executable_path_is_not_portable() -> None:
    candidate = DiscoveryCandidate(
        component_type=ComponentType.HOOK,
        local_name="local-hook",
        correlation_identity=None,
        launch_fingerprint=None,
        evidence=[
            DiscoveryEvidence(
                component=DiscoveredHook(
                    "local-hook", "PreToolUse", "command", {"command": "/Users/alice/hook.sh"}, "Hook", "test"
                ),
                provider=ProviderKind.HARNESS,
                scope=DiscoveryScope.PROJECT,
                harness="kiro",
            )
        ],
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
    )

    with pytest.raises(RegistrationPayloadError, match="local executable"):
        build_discovery_draft_payload(candidate, owner="alice")


def test_client_mutation_outcome_is_typed() -> None:
    conflict = CliError(ErrorCategory.CONFLICT, "Conflict", "Create", http_status=409)
    uncertain = CliError(ErrorCategory.UNAVAILABLE, "Timeout", "Create")

    conflict_result = client.run_mutation_once(Mock(side_effect=conflict))
    uncertain_result = client.run_mutation_once(Mock(side_effect=uncertain))
    success_result = client.run_mutation_once(Mock(return_value={"id": "one"}))

    assert conflict_result.status is client.MutationStatus.CONFLICT
    assert conflict_result.error is conflict
    assert uncertain_result.status is client.MutationStatus.UNCERTAIN
    assert success_result.status is client.MutationStatus.SUCCESS
    assert success_result.data == {"id": "one"}
