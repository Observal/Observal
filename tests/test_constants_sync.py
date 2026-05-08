"""Verify that observal_cli.constants and ide_registry stay in sync with server."""

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


def test_ide_registry_match():
    """IDE_REGISTRY must be identical between server and CLI."""
    server_reg = importlib.import_module("schemas.ide_registry")
    cli_reg = importlib.import_module("observal_cli.ide_registry")
    assert server_reg.IDE_REGISTRY.keys() == cli_reg.IDE_REGISTRY.keys(), (
        f"IDE_REGISTRY key mismatch: "
        f"server={sorted(server_reg.IDE_REGISTRY.keys())}, "
        f"cli={sorted(cli_reg.IDE_REGISTRY.keys())}"
    )
    for ide in server_reg.IDE_REGISTRY:
        server_spec = server_reg.IDE_REGISTRY[ide]
        cli_spec = cli_reg.IDE_REGISTRY[ide]
        for key in server_spec:
            assert key in cli_spec, f"IDE_REGISTRY[{ide!r}] missing key {key!r} in CLI"
            assert server_spec[key] == cli_spec[key], (
                f"IDE_REGISTRY[{ide!r}][{key!r}] mismatch: server={server_spec[key]!r}, cli={cli_spec[key]!r}"
            )


def test_ide_registry_model_choice_fields():
    """Every IDE must declare accepts_model_choice + auto_sentinel."""
    server_reg = importlib.import_module("schemas.ide_registry")
    cli_reg = importlib.import_module("observal_cli.ide_registry")
    expected_accepts = {
        "claude-code": True,
        "kiro": True,
        "codex": True,
        "gemini-cli": True,
        "opencode": True,
        "cursor": False,
        "vscode": False,
        "copilot": False,
        "copilot-cli": False,
    }
    for reg_name, reg in (("server", server_reg.IDE_REGISTRY), ("cli", cli_reg.IDE_REGISTRY)):
        for ide, accepts in expected_accepts.items():
            spec = reg[ide]
            assert "accepts_model_choice" in spec, f"{reg_name}: {ide} missing accepts_model_choice"
            assert "auto_sentinel" in spec, f"{reg_name}: {ide} missing auto_sentinel"
            assert spec["accepts_model_choice"] is accepts, (
                f"{reg_name}: {ide}.accepts_model_choice={spec['accepts_model_choice']!r}, expected {accepts!r}"
            )
            if accepts:
                assert isinstance(spec["auto_sentinel"], dict), (
                    f"{reg_name}: {ide} accepts_model_choice but auto_sentinel is not a dict"
                )
            else:
                assert spec["auto_sentinel"] is None, (
                    f"{reg_name}: {ide} does not accept_model_choice; auto_sentinel must be None"
                )
