# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Verify that observal_cli.constants and harness_registry stay in sync with server."""

import importlib

import pytest

_SHARED_LISTS = [
    "VALID_HARNESSES",
    "VALID_MCP_CATEGORIES",
    "VALID_MCP_TRANSPORTS",
    "VALID_MCP_FRAMEWORKS",
    "VALID_SKILL_TASK_TYPES",
    "VALID_HOOK_EVENTS",
    "VALID_HOOK_HANDLER_TYPES",
    "VALID_HOOK_EXECUTION_MODES",
    "VALID_HOOK_SCOPES",
    "VALID_PROMPT_CATEGORIES",
    "VALID_SANDBOX_RUNTIME_TYPES",
    "VALID_SANDBOX_NETWORK_POLICIES",
    "HARNESS_CAPABILITY_NAMES",
]


@pytest.mark.parametrize("name", _SHARED_LISTS)
def test_constants_match(name):
    server = importlib.import_module("schemas.constants")
    cli = importlib.import_module("observal_cli.constants")
    server_val = getattr(server, name)
    cli_val = getattr(cli, name)
    assert server_val == cli_val, f"{name} mismatch: server={server_val!r}, cli={cli_val!r}"


def test_harness_capability_matrix_match():
    """HARNESS_CAPABILITIES uses sets, so compare per-harness."""
    server = importlib.import_module("schemas.constants")
    cli = importlib.import_module("observal_cli.constants")
    server_val = server.HARNESS_CAPABILITIES
    cli_val = cli.HARNESS_CAPABILITIES
    assert server_val.keys() == cli_val.keys(), (
        f"HARNESS_CAPABILITIES key mismatch: server={sorted(server_val.keys())}, cli={sorted(cli_val.keys())}"
    )
    for harness in server_val:
        assert server_val[harness] == cli_val[harness], (
            f"HARNESS_CAPABILITIES[{harness!r}] mismatch: server={server_val[harness]!r}, cli={cli_val[harness]!r}"
        )


def test_harness_registry_match():
    """HARNESS_REGISTRY must be harnessntical between server and CLI."""
    server_reg = importlib.import_module("schemas.harness_registry")
    cli_reg = importlib.import_module("observal_cli.harness_registry")
    assert server_reg.HARNESS_REGISTRY.keys() == cli_reg.HARNESS_REGISTRY.keys(), (
        f"HARNESS_REGISTRY key mismatch: "
        f"server={sorted(server_reg.HARNESS_REGISTRY.keys())}, "
        f"cli={sorted(cli_reg.HARNESS_REGISTRY.keys())}"
    )
    for harness in server_reg.HARNESS_REGISTRY:
        server_spec = server_reg.HARNESS_REGISTRY[harness]
        cli_spec = cli_reg.HARNESS_REGISTRY[harness]
        for key in server_spec:
            assert key in cli_spec, f"HARNESS_REGISTRY[{harness!r}] missing key {key!r} in CLI"
            assert server_spec[key] == cli_spec[key], (
                f"HARNESS_REGISTRY[{harness!r}][{key!r}] mismatch: server={server_spec[key]!r}, cli={cli_spec[key]!r}"
            )
