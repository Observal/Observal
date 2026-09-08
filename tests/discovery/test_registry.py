# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from observal_cli import client
from observal_cli.discovery.models import (
    ComponentType,
    Confidence,
    DiscoveryCandidate,
    ReasonCode,
    RegistrationStatus,
    RegistryStatus,
    SupportStatus,
)
from observal_cli.discovery.registry import classify_registry_candidates
from observal_cli.errors import CliError, ErrorCategory


def _candidate(name: str = "Search Tool", component_type: ComponentType | None = ComponentType.MCP):
    return DiscoveryCandidate(
        component_type=component_type,
        local_name=name,
        correlation_identity="npm:search-tool",
        launch_fingerprint="sha256:" + "1" * 64,
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
        confidence=Confidence.HIGH,
    )


def _failure() -> CliError:
    return CliError(ErrorCategory.UNAVAILABLE, "failed", "Registry lookup")


def test_package_only_candidate_performs_no_registry_calls(monkeypatch):
    candidate = _candidate(component_type=None)
    candidate.registration_status = RegistrationStatus.NOT_APPLICABLE
    get = MagicMock(side_effect=AssertionError("unexpected request"))
    monkeypatch.setattr("observal_cli.discovery.registry.client.get", get)

    assert (
        classify_registry_candidates(
            [candidate], configuration={"server_url": "https://registry", "access_token": "token"}
        )
        == []
    )
    assert candidate.registry_status is RegistryStatus.NOT_CHECKED
    assert candidate.registration_status is RegistrationStatus.NOT_APPLICABLE
    get.assert_not_called()


def test_empty_candidate_list_performs_no_registry_calls(monkeypatch):
    get = MagicMock(side_effect=AssertionError("unexpected request"))
    monkeypatch.setattr("observal_cli.discovery.registry.client.get", get)

    assert (
        classify_registry_candidates([], configuration={"server_url": "https://registry", "access_token": "token"})
        == []
    )


def test_missing_configuration_and_auth_do_not_make_requests(monkeypatch):
    get = MagicMock(side_effect=AssertionError("unexpected request"))
    monkeypatch.setattr("observal_cli.discovery.registry.client.get", get)

    not_configured = _candidate()
    diagnostics = classify_registry_candidates([not_configured], configuration={})
    assert not_configured.registry_status is RegistryStatus.NOT_CHECKED
    assert not_configured.registration_status is RegistrationStatus.REQUIRES_AUTH
    assert not_configured.reason_codes == [ReasonCode.REGISTRY_NOT_CONFIGURED]
    assert diagnostics[0].code.value == "registry_not_configured"

    unauthenticated = _candidate()
    diagnostics = classify_registry_candidates(
        [unauthenticated], configuration={"server_url": "https://registry", "access_token": ""}
    )
    assert unauthenticated.registry_status is RegistryStatus.NOT_CHECKED
    assert unauthenticated.registration_status is RegistrationStatus.REQUIRES_AUTH
    assert unauthenticated.reason_codes == [ReasonCode.REGISTRY_AUTH_REQUIRED]
    assert diagnostics[0].code.value == "registry_auth_required"


@pytest.mark.parametrize(
    ("component_type", "my_path"),
    [
        (ComponentType.AGENT, "/api/v1/agents/my"),
        (ComponentType.MCP, "/api/v1/mcps/my"),
        (ComponentType.SKILL, "/api/v1/skills/my"),
        (ComponentType.HOOK, "/api/v1/hooks/my"),
    ],
)
def test_registry_uses_type_specific_owned_routes(monkeypatch, component_type, my_path):
    candidate = _candidate(component_type=component_type)
    get = MagicMock(side_effect=[{"username": "alice"}, []])
    monkeypatch.setattr("observal_cli.discovery.registry.client.get", get)
    monkeypatch.setattr(
        "observal_cli.discovery.registry.client.get_optional",
        MagicMock(return_value=client.OptionalLookupResult(client.OptionalLookupStatus.NOT_FOUND)),
    )

    classify_registry_candidates([candidate], configuration={"server_url": "https://registry", "access_token": "token"})

    assert get.call_args_list[1] == call(
        my_path,
        operation=f"List owned {component_type.value} Registry entries",
        resource=f"owned {component_type.value} entries",
    )
    assert candidate.registry_status is RegistryStatus.NO_EXACT_MATCH


def test_successful_owned_and_exact_404_classifies_owned_existing(monkeypatch):
    candidate = _candidate()
    get = MagicMock(
        side_effect=[
            {"username": "Alice"},
            [
                {
                    "id": "mcp-1",
                    "qualified_name": "alice/search-tool",
                    "status": "rejected",
                    "version": "1.2.0",
                }
            ],
        ]
    )
    optional = MagicMock(return_value=client.OptionalLookupResult(client.OptionalLookupStatus.NOT_FOUND))
    monkeypatch.setattr("observal_cli.discovery.registry.client.get", get)
    monkeypatch.setattr("observal_cli.discovery.registry.client.get_optional", optional)

    diagnostics = classify_registry_candidates(
        [candidate], configuration={"server_url": "https://registry", "access_token": "token"}
    )

    assert diagnostics == []
    assert candidate.registry_status is RegistryStatus.OWNED_EXISTING
    assert candidate.registration_status is RegistrationStatus.ALREADY_EXISTS
    assert candidate.reason_codes == [ReasonCode.REGISTRY_OWNED_EXISTING]
    assert candidate.registry_match is not None
    assert candidate.registry_match.id == "mcp-1"
    assert candidate.registry_match.status == "rejected"
    assert candidate.registry_match.owned is True
    assert candidate.registry_match.version == "1.2.0"
    optional.assert_called_once_with(
        "/api/v1/registry/resolve",
        params={"type": "mcp", "identifier": "alice/search-tool"},
        operation="Resolve exact mcp Registry identity",
        resource="alice/search-tool",
    )


def test_exact_unowned_match_fetches_detail(monkeypatch):
    candidate = _candidate()
    get = MagicMock(
        side_effect=[
            {"username": "alice"},
            [],
            {
                "id": "mcp-2",
                "qualified_name": "alice/search-tool",
                "status": "approved",
                "version": "2.0.0",
            },
        ]
    )
    optional = MagicMock(
        return_value=client.OptionalLookupResult(
            client.OptionalLookupStatus.FOUND,
            {
                "id": "mcp-2",
                "type": "mcp",
                "qualified_name": "alice/search-tool",
            },
        )
    )
    monkeypatch.setattr("observal_cli.discovery.registry.client.get", get)
    monkeypatch.setattr("observal_cli.discovery.registry.client.get_optional", optional)

    assert (
        classify_registry_candidates(
            [candidate], configuration={"server_url": "https://registry", "access_token": "token"}
        )
        == []
    )

    assert candidate.registry_status is RegistryStatus.EXACT_MATCH
    assert candidate.registration_status is RegistrationStatus.ALREADY_EXISTS
    assert candidate.registry_match is not None
    assert candidate.registry_match.owned is False
    assert candidate.registry_match.version == "2.0.0"
    assert get.call_args_list[-1] == call(
        "/api/v1/mcps/mcp-2",
        operation="Fetch exact mcp Registry entry",
        resource="alice/search-tool",
    )


def test_successful_complete_owned_list_and_exact_404_proves_no_match(monkeypatch):
    candidate = _candidate()
    candidate.registry_status = RegistryStatus.UNAVAILABLE
    candidate.registration_status = RegistrationStatus.NOT_APPLICABLE
    candidate.reason_codes = [ReasonCode.REGISTRY_UNAVAILABLE]
    monkeypatch.setattr(
        "observal_cli.discovery.registry.client.get",
        MagicMock(side_effect=[{"username": "alice"}, []]),
    )
    monkeypatch.setattr(
        "observal_cli.discovery.registry.client.get_optional",
        MagicMock(return_value=client.OptionalLookupResult(client.OptionalLookupStatus.NOT_FOUND)),
    )

    classify_registry_candidates([candidate], configuration={"server_url": "https://registry", "access_token": "token"})

    assert candidate.registry_status is RegistryStatus.NO_EXACT_MATCH
    assert candidate.registration_status is RegistrationStatus.ELIGIBLE
    assert candidate.reason_codes == [ReasonCode.NO_EXACT_REGISTRY_MATCH]
    assert candidate.registry_match is None


def test_get_failures_never_collapse_to_no_exact_match(monkeypatch):
    candidate = _candidate()
    monkeypatch.setattr("observal_cli.discovery.registry.client.get", MagicMock(side_effect=_failure()))

    diagnostics = classify_registry_candidates(
        [candidate], configuration={"server_url": "https://registry", "access_token": "token"}
    )

    assert candidate.registry_status is RegistryStatus.UNAVAILABLE
    assert candidate.registration_status is RegistrationStatus.NOT_APPLICABLE
    assert candidate.reason_codes == [ReasonCode.REGISTRY_UNAVAILABLE]
    assert diagnostics[0].code.value == "registry_unavailable"


def test_exact_transport_or_authorization_failure_never_proves_absence(monkeypatch):
    candidate = _candidate()
    monkeypatch.setattr(
        "observal_cli.discovery.registry.client.get",
        MagicMock(side_effect=[{"username": "alice"}, []]),
    )
    monkeypatch.setattr("observal_cli.discovery.registry.client.get_optional", MagicMock(side_effect=_failure()))

    diagnostics = classify_registry_candidates(
        [candidate], configuration={"server_url": "https://registry", "access_token": "token"}
    )

    assert candidate.registry_status is RegistryStatus.UNAVAILABLE
    assert candidate.registration_status is RegistrationStatus.NOT_APPLICABLE
    assert candidate.reason_codes == [ReasonCode.REGISTRY_UNAVAILABLE]
    assert diagnostics[0].code.value == "registry_unavailable"


def test_owned_list_and_exact_response_must_be_complete(monkeypatch):
    malformed_list_candidate = _candidate()
    get = MagicMock(side_effect=[{"username": "alice"}, {"items": []}])
    monkeypatch.setattr("observal_cli.discovery.registry.client.get", get)

    diagnostics = classify_registry_candidates(
        [malformed_list_candidate], configuration={"server_url": "https://registry", "access_token": "token"}
    )
    assert malformed_list_candidate.registry_status is RegistryStatus.UNAVAILABLE
    assert malformed_list_candidate.reason_codes == [ReasonCode.REGISTRY_LOOKUP_INCOMPLETE]
    assert diagnostics[0].code.value == "registry_lookup_incomplete"

    malformed_exact_candidate = _candidate()
    monkeypatch.setattr(
        "observal_cli.discovery.registry.client.get",
        MagicMock(side_effect=[{"username": "alice"}, []]),
    )
    monkeypatch.setattr(
        "observal_cli.discovery.registry.client.get_optional",
        MagicMock(return_value=client.OptionalLookupResult(client.OptionalLookupStatus.FOUND, {"id": "mcp-1"})),
    )
    diagnostics = classify_registry_candidates(
        [malformed_exact_candidate],
        configuration={"server_url": "https://registry", "access_token": "token"},
    )
    assert malformed_exact_candidate.registry_status is RegistryStatus.UNAVAILABLE
    assert malformed_exact_candidate.reason_codes == [ReasonCode.REGISTRY_LOOKUP_INCOMPLETE]
    assert diagnostics[0].code.value == "registry_lookup_incomplete"


def test_duplicate_owned_identity_and_disagreeing_ids_are_ambiguous(monkeypatch):
    owned_item = {
        "id": "mcp-owned",
        "qualified_name": "alice/search-tool",
        "status": "draft",
    }
    exact = client.OptionalLookupResult(
        client.OptionalLookupStatus.FOUND,
        {"id": "mcp-other", "type": "mcp", "qualified_name": "alice/search-tool"},
    )
    duplicate = _candidate()
    monkeypatch.setattr(
        "observal_cli.discovery.registry.client.get",
        MagicMock(side_effect=[{"username": "alice"}, [owned_item, dict(owned_item)]]),
    )
    monkeypatch.setattr("observal_cli.discovery.registry.client.get_optional", MagicMock(return_value=exact))
    classify_registry_candidates([duplicate], configuration={"server_url": "https://registry", "access_token": "token"})
    assert duplicate.registry_status is RegistryStatus.AMBIGUOUS
    assert duplicate.reason_codes == [ReasonCode.REGISTRY_AMBIGUOUS]

    disagreement = _candidate()
    monkeypatch.setattr(
        "observal_cli.discovery.registry.client.get",
        MagicMock(side_effect=[{"username": "alice"}, [owned_item]]),
    )
    classify_registry_candidates(
        [disagreement], configuration={"server_url": "https://registry", "access_token": "token"}
    )
    assert disagreement.registry_status is RegistryStatus.AMBIGUOUS
    assert disagreement.reason_codes == [ReasonCode.REGISTRY_AMBIGUOUS]


def test_candidates_share_owned_and_exact_requests_by_type_and_target(monkeypatch):
    first = _candidate()
    second = _candidate()
    get = MagicMock(side_effect=[{"username": "alice"}, []])
    optional = MagicMock(return_value=client.OptionalLookupResult(client.OptionalLookupStatus.NOT_FOUND))
    monkeypatch.setattr("observal_cli.discovery.registry.client.get", get)
    monkeypatch.setattr("observal_cli.discovery.registry.client.get_optional", optional)

    classify_registry_candidates(
        [first, second], configuration={"server_url": "https://registry", "access_token": "token"}
    )

    assert get.call_count == 2
    optional.assert_called_once()
    assert first.registry_status is second.registry_status is RegistryStatus.NO_EXACT_MATCH


def test_invalid_namespace_or_candidate_slug_fails_closed(monkeypatch):
    namespace_candidate = _candidate()
    monkeypatch.setattr(
        "observal_cli.discovery.registry.client.get",
        MagicMock(return_value={"username": "not valid"}),
    )
    diagnostics = classify_registry_candidates(
        [namespace_candidate], configuration={"server_url": "https://registry", "access_token": "token"}
    )
    assert namespace_candidate.registry_status is RegistryStatus.UNAVAILABLE
    assert namespace_candidate.reason_codes == [ReasonCode.REGISTRY_LOOKUP_INCOMPLETE]
    assert diagnostics[0].code.value == "registry_lookup_incomplete"

    slug_candidate = _candidate("!!!")
    monkeypatch.setattr(
        "observal_cli.discovery.registry.client.get",
        MagicMock(side_effect=[{"username": "alice"}, []]),
    )
    diagnostics = classify_registry_candidates(
        [slug_candidate], configuration={"server_url": "https://registry", "access_token": "token"}
    )
    assert slug_candidate.registry_status is RegistryStatus.UNAVAILABLE
    assert slug_candidate.reason_codes == [ReasonCode.REGISTRY_LOOKUP_INCOMPLETE]
    assert diagnostics[0].code.value == "registry_lookup_incomplete"


def test_ineligible_candidates_remain_ineligible_without_auth(monkeypatch):
    candidate = _candidate()
    candidate.registration_status = RegistrationStatus.INCOMPLETE
    candidate.missing_fields = ["launch"]
    monkeypatch.setattr(
        "observal_cli.discovery.registry.client.get",
        MagicMock(side_effect=AssertionError("unexpected request")),
    )

    classify_registry_candidates([candidate], configuration={})

    assert candidate.registration_status is RegistrationStatus.INCOMPLETE
    assert candidate.registry_status is RegistryStatus.NOT_CHECKED
