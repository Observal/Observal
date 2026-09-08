# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

import pytest

from observal_cli.discovery.models import LaunchKind, SanitizedLaunch
from observal_cli.discovery.normalize import (
    canonical_launch_document,
    canonicalize_python_package_name,
    fingerprint_launch,
    normalize_launch,
    normalize_mcp_definition,
    serialize_canonical_launch,
    split_npm_package_spec,
)


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        ("server", ("server", None)),
        ("server@latest", ("server", "latest")),
        ("@scope/server", ("@scope/server", None)),
        ("@scope/server@1.2.3", ("@scope/server", "1.2.3")),
        ("alias@npm:server", None),
        ("https://example.test/server.tgz", None),
    ],
)
def test_npm_package_parsing(requirement: str, expected: tuple[str, str | None] | None) -> None:
    assert split_npm_package_spec(requirement) == expected


def test_npx_and_npm_exec_have_the_same_identity_and_launch() -> None:
    npx = normalize_launch(command="npx", arguments=["-y", "@scope/server@1.2.3", "--mode", "read"])
    npm = normalize_launch(command="npm", arguments=["exec", "--yes", "--", "@scope/server@1.2.3", "--mode", "read"])

    assert npx.complete and npm.complete
    assert npx.correlation_identity == npm.correlation_identity == "npm:@scope/server"
    assert npx.launch == npm.launch
    assert npx.launch_fingerprint == npm.launch_fingerprint


def test_behaviorally_different_arguments_produce_different_fingerprints() -> None:
    read = normalize_launch(command="npx", arguments=["server", "--mode", "read"])
    write = normalize_launch(command="npx", arguments=["server", "--mode", "write"])

    assert read.correlation_identity == write.correlation_identity == "npm:server"
    assert read.launch_fingerprint != write.launch_fingerprint


def test_mcp_definition_behavior_fields_are_part_of_the_fingerprint() -> None:
    base = {"command": "npx", "args": ["server", "--mode", "read"]}
    variants = [
        base,
        {**base, "args": ["server", "--mode", "write"]},
        {**base, "env": {"API_KEY": "secret"}},
        {**base, "headers": {"Authorization": "secret"}},
        {**base, "transport": "stdio"},
    ]

    fingerprints = {normalize_mcp_definition(item).launch_fingerprint for item in variants}

    assert None not in fingerprints
    assert len(fingerprints) == len(variants)


@pytest.mark.parametrize(
    ("metadata", "reason"),
    [
        ({"env": "API_KEY=secret"}, "malformed_environment"),
        ({"headers": "Authorization: secret"}, "malformed_headers"),
        ({"transport": "future-custom-transport"}, "unsupported_transport"),
        ({"type": None}, "malformed_transport"),
        ({"env": {}, "environment": {}}, "ambiguous_environment_metadata"),
    ],
)
def test_malformed_or_unsupported_mcp_metadata_omits_fingerprint(metadata: dict, reason: str) -> None:
    result = normalize_mcp_definition({"command": "npx", "args": ["server"], **metadata})

    assert not result.complete
    assert result.launch_fingerprint is None
    assert result.reason == reason


def test_legacy_http_transport_normalizes_to_streamable_http() -> None:
    result = normalize_mcp_definition({"url": "https://example.test/mcp", "transport": "http"})

    assert result.complete
    assert result.launch is not None
    assert result.launch.transport == "streamable-http"
    assert result.launch_fingerprint is not None


def test_registry_requirement_lists_and_harness_mappings_normalize_identically() -> None:
    installed = normalize_mcp_definition(
        {
            "command": "npx",
            "args": ["server"],
            "environment_variables": [{"name": "API_KEY", "required": True}],
            "headers": [{"name": "Authorization", "required": True}],
            "type": "stdio",
        }
    )
    discovered = normalize_mcp_definition(
        {
            "command": "npx",
            "args": ["server"],
            "env": {"API_KEY": "different-secret"},
            "httpHeaders": {"Authorization": "Bearer different-secret"},
            "transport": "stdio",
        }
    )

    assert installed.complete and discovered.complete
    assert installed.launch == discovered.launch
    assert installed.launch_fingerprint == discovered.launch_fingerprint


def test_secret_values_are_replaced_before_fingerprinting() -> None:
    first = normalize_launch(
        command="npx",
        arguments=["server", "--token", "first-secret-value"],
        environment={"API_KEY": "first-environment-secret", "MODE": "read"},
        headers={"Authorization": "Bearer first-header-secret"},
    )
    second = normalize_launch(
        command="npx",
        arguments=["server", "--token", "second-secret-value"],
        environment={"API_KEY": "second-environment-secret", "MODE": "write"},
        headers={"Authorization": "Bearer second-header-secret"},
    )

    assert first.complete and second.complete
    assert first.launch_fingerprint == second.launch_fingerprint
    canonical = serialize_canonical_launch(first.launch)  # type: ignore[arg-type]
    assert "first-secret" not in canonical
    assert "first-environment" not in canonical
    assert "first-header" not in canonical
    assert json.loads(canonical)["arguments"] == ["--token", "<secret>"]
    assert json.loads(canonical)["environment_names"] == ["API_KEY", "MODE"]
    assert json.loads(canonical)["header_names"] == ["Authorization"]


def test_canonical_serialization_is_compact_sorted_utf8() -> None:
    result = normalize_launch(command="npx", arguments=["server", "--label", "café"], environment=["Z", "A"])

    serialized = serialize_canonical_launch(result.launch)  # type: ignore[arg-type]

    assert serialized == (
        '{"arguments":["--label","café"],"binary":"server","environment_names":["A","Z"],'
        '"kind":"npm","package":"server"}'
    )
    assert fingerprint_launch(result.launch).startswith("sha256:")  # type: ignore[arg-type]
    assert len(fingerprint_launch(result.launch)) == 71  # type: ignore[arg-type]


def test_canonicalizer_redacts_manual_secret_arguments_and_rejects_secret_identity() -> None:
    first = SanitizedLaunch(kind=LaunchKind.NPM, package="server", arguments=("--token", "first-value"))
    second = SanitizedLaunch(kind=LaunchKind.NPM, package="server", arguments=("--token", "second-value"))

    assert serialize_canonical_launch(first) == serialize_canonical_launch(second)
    assert "first-value" not in serialize_canonical_launch(first)
    with pytest.raises(ValueError, match="package is not safely canonicalizable"):
        canonical_launch_document(
            SanitizedLaunch(kind=LaunchKind.NPM, package="ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd")
        )


def test_uv_requirements_use_pep503_identity_and_retain_metadata() -> None:
    result = normalize_launch(command="uv", arguments=["tool", "run", "MCP_Server.Fetch[cli]>=0.6", "--mode", "read"])

    assert result.complete
    assert result.correlation_identity == "pypi:mcp-server-fetch"
    assert result.launch is not None
    assert result.launch.kind is LaunchKind.UV
    assert result.launch.requirement == "mcp-server-fetch[cli]>=0.6"
    assert result.launch.version == ">=0.6"
    assert canonicalize_python_package_name("MCP_Server.Fetch") == "mcp-server-fetch"


def test_uv_at_version_and_known_pipx_executable_correlate() -> None:
    uv = normalize_launch(command="uvx", arguments=["mcp-server-fetch@0.6.2"])
    pipx = normalize_launch(
        command="mcp-fetch",
        known_pipx_executables={"mcp-fetch": {"package": "mcp_server_fetch", "version": "0.6.2"}},
    )

    assert uv.correlation_identity == pipx.correlation_identity == "pypi:mcp-server-fetch"
    assert uv.launch is not None and uv.launch.version == "0.6.2"
    assert pipx.launch is not None and pipx.launch.kind is LaunchKind.PIPX


def test_python_module_launch_is_supported() -> None:
    result = normalize_launch(command="python3", arguments=["-m", "package.server", "--mode", "read"])

    assert result.complete
    assert result.correlation_identity == "python:package.server"
    assert result.launch is not None
    assert canonical_launch_document(result.launch)["module"] == "package.server"


def test_node_script_must_resolve_inside_source_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    inside = normalize_launch(command="node", arguments=["scripts/server.js"], source_root=root, working_dir=root)
    outside = normalize_launch(command="node", arguments=["../secret/server.js"], source_root=root, working_dir=root)

    assert inside.complete
    assert inside.correlation_identity == "node:scripts/server.js"
    assert inside.launch is not None and inside.launch.script == "scripts/server.js"
    assert not outside.complete
    assert outside.launch_fingerprint is None
    assert outside.reason == "script_outside_source_root"


def test_url_identity_is_normalized_and_secret_independent() -> None:
    first = normalize_launch(
        url="HTTPS://user:password@Example.COM:443/mcp/?token=first&mode=read#fragment",
        headers={"X-API-Key": "first"},
    )
    second = normalize_launch(
        url="https://example.com/mcp?mode=read&token=second",
        headers={"X-API-Key": "second"},
    )

    assert first.complete and second.complete
    assert first.correlation_identity == second.correlation_identity == "url:https://example.com/mcp"
    assert first.launch_fingerprint == second.launch_fingerprint
    assert first.launch is not None
    assert first.launch.url == "https://example.com/mcp?mode=read"
    assert "password" not in serialize_canonical_launch(first.launch)


@pytest.mark.parametrize(
    ("command", "arguments", "reason"),
    [
        ("sh", ["-c", "npx server"], "shell_wrapper_unsupported"),
        ("bash -c npx server", [], "shell_command_string_unsupported"),
        ("npm", ["exec", "server"], "npm_exec_separator_required"),
        ("uv", ["run", "server"], "unsupported_uv_invocation"),
        ("unknown-tool", [], "unknown_executable"),
    ],
)
def test_unsupported_or_ambiguous_launches_have_no_fingerprint(command: str, arguments: list[str], reason: str) -> None:
    result = normalize_launch(command=command, arguments=arguments)

    assert not result.complete
    assert result.launch_fingerprint is None
    assert result.reason == reason
