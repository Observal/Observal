"""Verify that observal_cli.constants stays in sync with schemas.constants."""

import importlib

import pytest

_SHARED_LISTS = [
    "VALID_IDES",
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
    "IDE_FEATURES",
]


@pytest.mark.parametrize("name", _SHARED_LISTS)
def test_constants_match(name):
    server = importlib.import_module("schemas.constants")
    cli = importlib.import_module("observal_cli.constants")
    server_val = getattr(server, name)
    cli_val = getattr(cli, name)
    assert server_val == cli_val, f"{name} mismatch: server={server_val!r}, cli={cli_val!r}"


def test_ide_feature_matrix_match():
    """IDE_FEATURE_MATRIX uses sets, so compare per-IDE."""
    server = importlib.import_module("schemas.constants")
    cli = importlib.import_module("observal_cli.constants")
    server_val = server.IDE_FEATURE_MATRIX
    cli_val = cli.IDE_FEATURE_MATRIX
    assert server_val.keys() == cli_val.keys(), (
        f"IDE_FEATURE_MATRIX key mismatch: server={sorted(server_val.keys())}, cli={sorted(cli_val.keys())}"
    )
    for ide in server_val:
        assert server_val[ide] == cli_val[ide], (
            f"IDE_FEATURE_MATRIX[{ide!r}] mismatch: server={server_val[ide]!r}, cli={cli_val[ide]!r}"
        )
