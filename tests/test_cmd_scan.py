# SPDX-FileCopyrightText: 2026 Anupam Kumar <anupam9594.kumar@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 VishnuM049 <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Behavioral tests for the ``observal scan`` command."""

from __future__ import annotations

import inspect
import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock, call

import pytest
import typer
from typer.testing import CliRunner

import observal_cli.cmd_scan as cmd_scan
import observal_cli.discovery.collector as discovery_collector
from observal_cli import client, config
from observal_cli.discovery.collector import DiscoveryScanCollection, HarnessStatus
from observal_cli.discovery.models import (
    ComponentType,
    Confidence,
    DiagnosticCode,
    DiagnosticSeverity,
    DiscoveryCandidate,
    DiscoveryDiagnostic,
    DiscoveryEvidence,
    DiscoveryScope,
    ProviderKind,
    ProviderResult,
    RegistrationStatus,
    RegistryStatus,
    SupportStatus,
)
from observal_cli.discovery.normalize import build_candidates
from observal_cli.harness import (
    DiscoveredAgent,
    DiscoveredHook,
    DiscoveredMcp,
    DiscoveredSkill,
    NotSupportedError,
    ScanResult,
)
from observal_cli.harness.cursor import CursorAdapter

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


class FakeTable:
    """Small rendering boundary that records table structure and values."""

    def __init__(self, title: str, **options):
        self.title = title
        self.options = options
        self.columns: list[tuple[str, dict]] = []
        self.rows: list[tuple[str, ...]] = []

    def add_column(self, name: str, **options) -> None:
        self.columns.append((name, options))

    def add_row(self, *values: str) -> None:
        self.rows.append(values)


class UnreadableRoot:
    def __init__(self, error: OSError):
        self.error = error

    def __str__(self) -> str:
        return "/unreadable/harness"

    def is_dir(self) -> bool:
        raise self.error


def _make_app() -> typer.Typer:
    app = typer.Typer()
    cmd_scan.register_scan(app)

    @app.command(name="noop")
    def noop() -> None:
        pass

    return app


def _invoke(*args: str):
    return runner.invoke(_make_app(), ["scan", *args])


def _adapter(
    *,
    home_result: ScanResult | None = None,
    project_result: ScanResult | None = None,
    project_results: list[ScanResult] | None = None,
    hook_status: str = "installed",
    resolved_home: Path | UnreadableRoot | None = None,
):
    scan_project = Mock(return_value=project_result or ScanResult())
    if project_results is not None:
        scan_project.side_effect = project_results
    return SimpleNamespace(
        resolve_home_dir=Mock(return_value=resolved_home),
        scan_home=Mock(return_value=home_result or ScanResult()),
        scan_project=scan_project,
        detect_hooks=Mock(return_value=hook_status),
    )


def _mcp(
    name: str,
    *,
    source: str,
    command: str | None = "npx",
    args: list[str] | None = None,
    url: str | None = None,
) -> DiscoveredMcp:
    return DiscoveredMcp(
        name=name,
        command=command,
        args=args or [],
        url=url,
        description=f"Description for {name}",
        source=source,
    )


def test_discovery_table_helpers_redact_secrets_and_absolute_paths(tmp_path: Path) -> None:
    secret = "ordinary-sensitive-value"
    mcp = _mcp(
        "remote",
        source=str(tmp_path / "outside" / "mcp.json"),
        command="npx",
        args=["--token", secret],
    )

    launch = cmd_scan._safe_discovery_mcp_launch(mcp)
    source = cmd_scan._safe_discovery_source(mcp.source, home=tmp_path / "home", project_dir=tmp_path / "project")

    assert secret not in launch
    assert "<secret>" in launch
    assert str(tmp_path) not in source
    assert source == "<external>/mcp.json"


def _skill(name: str, source: str) -> DiscoveredSkill:
    return DiscoveredSkill(name, f"Description for {name}", source, "general")


def _hook(name: str, source: str, event: str = "Stop") -> DiscoveredHook:
    return DiscoveredHook(name, event, "command", {"command": "true"}, f"Description for {name}", source)


def _agent(name: str, *, model: str = "model-a", description: str | None = None) -> DiscoveredAgent:
    return DiscoveredAgent(name, description or f"Description for {name}", model, "Prompt", f"/{name}.md")


@pytest.fixture
def scan_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(project)

    ensure_loaded = Mock()
    get_all_adapters = Mock(return_value={})
    get_adapter = Mock()
    trace = Mock()
    rprint = Mock()
    console_print = Mock()
    config_load = Mock(return_value={})
    save_aliases = Mock()
    save_last_results = Mock()
    registered_only = Mock(return_value=False)
    http_get = Mock(side_effect=AssertionError("unexpected registry request"))
    spinner_calls: list[str] = []
    tables: list[FakeTable] = []

    @contextmanager
    def spinner(message: str):
        spinner_calls.append(message)
        yield

    def table_factory(*args, **kwargs):
        table = FakeTable(*args, **kwargs)
        tables.append(table)
        return table

    monkeypatch.setattr(cmd_scan, "ensure_loaded", ensure_loaded)
    monkeypatch.setattr(cmd_scan, "get_all_adapters", get_all_adapters)
    monkeypatch.setattr(cmd_scan, "get_adapter", get_adapter)
    monkeypatch.setattr(cmd_scan, "optic", SimpleNamespace(trace=trace))
    monkeypatch.setattr(cmd_scan, "rprint", rprint)
    monkeypatch.setattr(cmd_scan.console, "print", console_print)
    monkeypatch.setattr(cmd_scan, "spinner", spinner)
    monkeypatch.setattr(cmd_scan, "Table", table_factory)
    monkeypatch.setattr(config, "load", config_load)
    monkeypatch.setattr(config, "save_aliases", save_aliases)
    monkeypatch.setattr(config, "save_last_results", save_last_results)
    monkeypatch.setattr(client, "get_registered_agents_only", registered_only)

    import httpx

    monkeypatch.setattr(httpx, "get", http_get)

    return SimpleNamespace(
        home=home,
        project=project,
        ensure_loaded=ensure_loaded,
        get_all=get_all_adapters,
        get_one=get_adapter,
        trace=trace,
        rprint=rprint,
        console_print=console_print,
        config_load=config_load,
        save_aliases=save_aliases,
        save_last_results=save_last_results,
        registered_only=registered_only,
        http_get=http_get,
        spinner_calls=spinner_calls,
        tables=tables,
    )


def test_register_scan_owns_command_and_option_aliases() -> None:
    app = typer.Typer()

    assert cmd_scan.register_scan(app) is None
    assert len(app.registered_commands) == 1
    command = app.registered_commands[0]
    assert command.name == "scan"

    parameters = inspect.signature(command.callback).parameters
    long_prefix = "-" * 2
    assert parameters["harness"].default.param_decls == (f"{long_prefix}harness", "-i")
    assert parameters["output"].default.param_decls == (f"{long_prefix}output", "-o")
    assert parameters["output"].default.default == "table"
    assert parameters["discover"].default.param_decls == (f"{long_prefix}discover",)
    assert parameters["discover"].default.default is False


def test_discover_json_uses_versioned_contract_and_never_calls_mutations(scan_env, monkeypatch) -> None:
    candidate = DiscoveryCandidate(
        component_type=ComponentType.MCP,
        local_name="search",
        correlation_identity="npm:search",
        launch_fingerprint="sha256:" + "1" * 64,
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
        registry_status=RegistryStatus.NO_EXACT_MATCH,
        confidence=Confidence.HIGH,
    )
    collection = DiscoveryScanCollection(
        harnesses=[HarnessStatus("kiro", "installed")],
        candidates=[candidate],
        diagnostics=[
            DiscoveryDiagnostic(
                DiagnosticCode.EXECUTABLE_MISSING,
                DiagnosticSeverity.WARNING,
                "npm",
                None,
                "npm executable is unavailable",
            )
        ],
    )
    collect = Mock(return_value=collection)
    mutation = Mock(side_effect=AssertionError("discover output must not mutate"))
    register = Mock(side_effect=AssertionError("JSON discovery must not enter registration"))
    monkeypatch.setattr(cmd_scan, "collect_discovery_scan", collect)
    monkeypatch.setattr(cmd_scan, "register_discovery_candidates", register)
    monkeypatch.setattr(client, "post", mutation)

    result = _invoke("--discover", "--output", "json")

    assert result.exit_code == 0, result.exception
    payload = json.loads(result.output)
    assert payload["discovery_schema_version"] == 1
    assert payload["candidates"][0]["local_name"] == "search"
    assert payload["candidates"][0]["registry_status"] == "no_exact_match"
    assert payload["diagnostics"][0]["code"] == "executable_missing"
    collect.assert_called_once_with({}, home=scan_env.home, project_dir=scan_env.project, harness_filtered=False)
    mutation.assert_not_called()
    register.assert_not_called()
    scan_env.http_get.assert_not_called()
    scan_env.rprint.assert_not_called()


def test_discover_json_never_reports_invalid_portable_source_as_eligible(scan_env, monkeypatch) -> None:
    evidence = DiscoveryEvidence(
        component=DiscoveredHook(
            "unsafe-hook",
            "UnsupportedEvent",
            "command",
            {"command": "/Users/alice/private/hook.sh", "args": []},
            "Unsafe local hook",
            "test",
        ),
        provider=ProviderKind.HARNESS,
        scope=DiscoveryScope.PROJECT,
        harness="kiro",
        display_path="<project>/.kiro/hooks/unsafe.json",
    )
    candidate = build_candidates([evidence])[0]
    collection = DiscoveryScanCollection(candidates=[candidate])
    register = Mock(side_effect=AssertionError("JSON discovery must not enter registration"))
    mutation = Mock(side_effect=AssertionError("JSON discovery must not mutate"))
    monkeypatch.setattr(cmd_scan, "collect_discovery_scan", Mock(return_value=collection))
    monkeypatch.setattr(cmd_scan, "register_discovery_candidates", register)
    monkeypatch.setattr(client, "post", mutation)

    result = _invoke("--discover", "--output", "json")

    assert result.exit_code == 0, result.exception
    serialized = json.loads(result.output)["candidates"][0]
    assert serialized["support_status"] == "unsupported"
    assert serialized["registration_status"] == "incomplete"
    assert serialized["registration_status"] != "eligible"
    assert serialized["reason_codes"] == ["unsupported_launch"]
    assert serialized["missing_fields"] == ["event"]
    register.assert_not_called()
    mutation.assert_not_called()


def test_discover_json_rejects_unsupported_mcp_transport_end_to_end(scan_env, monkeypatch) -> None:
    config_path = scan_env.project / ".cursor" / "mcp.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "remote": {
                        "url": "https://example.test/mcp",
                        "transport": "websocket",
                    }
                }
            }
        )
    )
    adapter = CursorAdapter()
    scan_env.get_all.return_value = {"cursor": adapter}
    empty_provider = Mock(return_value=ProviderResult())
    monkeypatch.setattr(discovery_collector, "discover_npm", empty_provider)
    monkeypatch.setattr(discovery_collector, "discover_pipx", empty_provider)
    monkeypatch.setattr(discovery_collector, "discover_uv", empty_provider)
    mutation = Mock(side_effect=AssertionError("unsupported transport must not mutate"))
    monkeypatch.setattr(client, "post", mutation)

    result = _invoke("--discover", "--output", "json")

    assert result.exit_code == 0, result.exception
    payload = json.loads(result.output)
    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["local_name"] == "remote"
    assert candidate["launch_fingerprint"] is None
    assert candidate["support_status"] == "unsupported"
    assert candidate["registration_status"] == "incomplete"
    assert candidate["missing_fields"] == ["portable_launch"]
    assert "unsupported_launch" in candidate["reason_codes"]
    assert any(item["code"] == "unsupported_launch" for item in payload["diagnostics"])
    mutation.assert_not_called()


def test_discover_table_renders_candidates_and_diagnostics_without_legacy_registry_query(scan_env, monkeypatch) -> None:
    candidate = DiscoveryCandidate(
        component_type=None,
        local_name="package-tool",
        correlation_identity="pypi:package-tool",
        launch_fingerprint="sha256:" + "2" * 64,
        support_status=SupportStatus.UNSUPPORTED,
        registration_status=RegistrationStatus.NOT_APPLICABLE,
        confidence=Confidence.LOW,
    )
    collection = DiscoveryScanCollection(
        candidates=[candidate],
        diagnostics=[
            DiscoveryDiagnostic(
                DiagnosticCode.REGISTRY_AUTH_REQUIRED,
                DiagnosticSeverity.WARNING,
                "registry",
                None,
                "Registry authentication is required",
            )
        ],
    )
    collect = Mock(return_value=collection)
    monkeypatch.setattr(cmd_scan, "collect_discovery_scan", collect)

    result = _invoke("--harness", "kiro", "--discover")

    assert result.exit_code == 0, result.exception
    assert [table.title for table in scan_env.tables] == [
        "Discovery Candidates (1)",
        "Discovery Diagnostics (1)",
    ]
    assert scan_env.tables[0].rows == [("unknown", "package-tool", "not_tracked", "not_checked", "not_applicable")]
    collect.assert_called_once_with(
        {"kiro": scan_env.get_one.return_value},
        home=scan_env.home,
        project_dir=scan_env.project,
        harness_filtered=True,
    )
    scan_env.http_get.assert_not_called()


def test_discover_table_non_tty_never_enters_registration(scan_env, monkeypatch) -> None:
    candidate = DiscoveryCandidate(
        component_type=ComponentType.AGENT,
        local_name="helper",
        correlation_identity=None,
        launch_fingerprint=None,
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
        registry_status=RegistryStatus.NO_EXACT_MATCH,
    )
    monkeypatch.setattr(
        cmd_scan,
        "collect_discovery_scan",
        Mock(return_value=DiscoveryScanCollection(candidates=[candidate])),
    )
    monkeypatch.setattr(cmd_scan, "_stdin_is_tty", Mock(return_value=False))
    register = Mock(side_effect=AssertionError("non-TTY discovery must not enter registration"))
    monkeypatch.setattr(cmd_scan, "register_discovery_candidates", register)

    result = _invoke("--discover")

    assert result.exit_code == 0, result.exception
    register.assert_not_called()


def test_discover_table_invokes_registration_only_for_tty(scan_env, monkeypatch) -> None:
    candidate = DiscoveryCandidate(
        component_type=ComponentType.AGENT,
        local_name="helper",
        correlation_identity=None,
        launch_fingerprint=None,
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
        registry_status=RegistryStatus.NO_EXACT_MATCH,
    )
    collection = DiscoveryScanCollection(candidates=[candidate])
    monkeypatch.setattr(cmd_scan, "collect_discovery_scan", Mock(return_value=collection))
    monkeypatch.setattr(cmd_scan, "_stdin_is_tty", Mock(return_value=True))
    register = Mock(return_value=[SimpleNamespace(failed=False)])
    render = Mock()
    monkeypatch.setattr(cmd_scan, "register_discovery_candidates", register)
    monkeypatch.setattr(cmd_scan, "render_registration_results", render)

    result = _invoke("--discover")

    assert result.exit_code == 0, result.exception
    register.assert_called_once_with([candidate], output="table", stdin_is_tty=True)
    render.assert_called_once_with(register.return_value)


def test_failed_discovery_registration_sets_nonzero_final_exit(scan_env, monkeypatch) -> None:
    candidate = DiscoveryCandidate(
        component_type=ComponentType.AGENT,
        local_name="helper",
        correlation_identity=None,
        launch_fingerprint=None,
        support_status=SupportStatus.SUPPORTED,
        registration_status=RegistrationStatus.ELIGIBLE,
        registry_status=RegistryStatus.NO_EXACT_MATCH,
    )
    monkeypatch.setattr(
        cmd_scan,
        "collect_discovery_scan",
        Mock(return_value=DiscoveryScanCollection(candidates=[candidate])),
    )
    monkeypatch.setattr(cmd_scan, "_stdin_is_tty", Mock(return_value=True))
    monkeypatch.setattr(
        cmd_scan,
        "register_discovery_candidates",
        Mock(return_value=[SimpleNamespace(failed=True)]),
    )
    monkeypatch.setattr(cmd_scan, "render_registration_results", Mock())

    result = _invoke("--discover")

    assert result.exit_code == 1


def test_discover_json_empty_state_includes_schema_and_diagnostics(scan_env, monkeypatch) -> None:
    collection = DiscoveryScanCollection(
        diagnostics=[
            DiscoveryDiagnostic(
                DiagnosticCode.EXECUTABLE_MISSING,
                DiagnosticSeverity.WARNING,
                "npm",
                None,
                "npm executable is unavailable",
            )
        ]
    )
    monkeypatch.setattr(cmd_scan, "collect_discovery_scan", Mock(return_value=collection))

    result = _invoke("--discover", "--output", "json")

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "discovery_schema_version": 1,
        "harnesses": [],
        "mcps": [],
        "skills": [],
        "hooks": [],
        "agents": [],
        "candidates": [],
        "diagnostics": [
            {
                "code": "executable_missing",
                "severity": "warning",
                "provider": "npm",
                "source": None,
                "message": "npm executable is unavailable",
            }
        ],
    }


def test_discover_table_shows_diagnostics_before_no_findings_exit(scan_env, monkeypatch) -> None:
    collection = DiscoveryScanCollection(
        diagnostics=[
            DiscoveryDiagnostic(
                DiagnosticCode.EXECUTABLE_MISSING,
                DiagnosticSeverity.WARNING,
                "npm",
                None,
                "npm executable is unavailable",
            )
        ]
    )
    monkeypatch.setattr(cmd_scan, "collect_discovery_scan", Mock(return_value=collection))

    result = _invoke("--discover")

    assert result.exit_code == 1
    assert [table.title for table in scan_env.tables] == ["Discovery Diagnostics (1)"]
    assert scan_env.rprint.call_args_list[-1] == call("[yellow]No harness configurations found.[/yellow]")


def test_unknown_harness_filter_lists_sorted_choices(scan_env) -> None:
    scan_env.get_one.side_effect = KeyError("unknown")
    scan_env.get_all.return_value = {"kiro": object(), "cursor": object()}

    result = _invoke("-i", "unknown")

    assert result.exit_code == 1
    scan_env.ensure_loaded.assert_called_once_with()
    scan_env.get_one.assert_called_once_with("unknown")
    scan_env.get_all.assert_called_once_with()
    assert scan_env.rprint.call_args_list == [
        call("[red]Unknown harness: unknown[/red]"),
        call("Valid harnesses: cursor, kiro"),
    ]


def test_short_filter_alias_scans_only_selected_static_home(scan_env) -> None:
    (scan_env.home / ".cursor").mkdir()
    cursor = _adapter()
    skipped = _adapter()
    scan_env.get_one.return_value = cursor
    scan_env.get_all.return_value = {"cursor": cursor, "kiro": skipped}

    result = _invoke("-i", "cursor", "-o", "table")

    assert result.exit_code == 0, result.exception
    assert scan_env.get_one.call_args_list == [call("cursor"), call("cursor")]
    scan_env.get_all.assert_not_called()
    cursor.scan_home.assert_called_once_with(scan_env.home)
    assert cursor.scan_project.call_args_list == [call(scan_env.project), call(scan_env.home)]
    cursor.detect_hooks.assert_called_once_with(scan_env.home / ".cursor")
    skipped.scan_home.assert_not_called()
    skipped.scan_project.assert_not_called()
    assert scan_env.spinner_calls == ["Scanning ~/.cursor..."]
    assert [table.title for table in scan_env.tables] == ["harnesses Detected"]


@pytest.mark.parametrize("output", ["table", "json"])
def test_missing_harness_roots_have_deterministic_empty_states(scan_env, output: str) -> None:
    adapter = _adapter()
    scan_env.get_all.return_value = {"cursor": adapter}

    result = _invoke("-o", output)

    adapter.resolve_home_dir.assert_called_once_with()
    adapter.scan_home.assert_not_called()
    adapter.detect_hooks.assert_not_called()
    assert adapter.scan_project.call_args_list == [call(scan_env.project), call(scan_env.home)]
    if output == "json":
        assert result.exit_code == 0
        assert json.loads(result.output) == {
            "harnesses": [],
            "mcps": [],
            "skills": [],
            "hooks": [],
            "agents": [],
        }
        scan_env.rprint.assert_not_called()
    else:
        assert result.exit_code == 1
        scan_env.rprint.assert_called_once_with("[yellow]No harness configurations found.[/yellow]")


def test_current_project_is_scanned_even_when_the_harness_home_is_absent(scan_env) -> None:
    adapter = _adapter(
        project_results=[
            ScanResult(mcps=[_mcp("project-server", source="project", args=["serve"])]),
            ScanResult(),
        ]
    )
    scan_env.get_all.return_value = {"cursor": adapter}

    result = _invoke()

    assert result.exit_code == 0, result.exception
    adapter.scan_home.assert_not_called()
    assert adapter.scan_project.call_args_list == [call(scan_env.project), call(scan_env.home)]
    assert [table.title for table in scan_env.tables] == ["MCP Servers (1)"]
    assert scan_env.tables[0].rows == [("project-server", "npx serve", "project")]
    assert scan_env.spinner_calls == []


def test_relocated_harness_controls_home_argument_label_and_hook_root(scan_env, tmp_path: Path) -> None:
    relocated = tmp_path / "goose-root"
    relocated.mkdir()
    adapter = _adapter(resolved_home=relocated)
    scan_env.get_all.return_value = {"goose": adapter}

    result = _invoke()

    assert result.exit_code == 0, result.exception
    adapter.scan_home.assert_called_once_with(None)
    adapter.detect_hooks.assert_called_once_with(relocated)
    assert adapter.scan_project.call_args_list == [call(scan_env.project), call(scan_env.home)]
    assert scan_env.spinner_calls == [f"Scanning {relocated}..."]


def test_unmapped_harness_uses_home_root_and_fallback_hook_directory(scan_env) -> None:
    adapter = _adapter()
    scan_env.get_all.return_value = {"custom": adapter}

    result = _invoke()

    assert result.exit_code == 0, result.exception
    adapter.scan_home.assert_called_once_with(scan_env.home)
    adapter.detect_hooks.assert_called_once_with(scan_env.home / ".config" / "custom")
    assert scan_env.spinner_calls == ["Scanning custom..."]


def test_home_is_not_scanned_twice_when_it_is_the_project(scan_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(scan_env.home)
    (scan_env.home / ".cursor").mkdir()
    adapter = _adapter()
    scan_env.get_all.return_value = {"cursor": adapter}

    result = _invoke("-o", "json")

    assert result.exit_code == 0
    adapter.scan_project.assert_called_once_with(scan_env.home)


def test_json_normalizes_components_and_mcp_precedence_across_all_scan_scopes(scan_env) -> None:
    (scan_env.home / ".cursor").mkdir()
    (scan_env.home / ".kiro").mkdir()

    shared_home = _mcp("shared", source="cursor:home", args=["home"])
    cursor = _adapter(
        home_result=ScanResult(
            mcps=[shared_home, _mcp("home-only", source="cursor:home")],
            skills=[_skill("home-skill", "cursor:home")],
            hooks=[_hook("home-hook", "cursor:home")],
            agents=[_agent("home-agent")],
        ),
        project_results=[
            ScanResult(
                mcps=[
                    _mcp("shared", source="cursor:project", args=["project"]),
                    _mcp("project-only", source="cursor:project"),
                ],
                skills=[_skill("project-skill", "cursor:project")],
                hooks=[_hook("project-hook", "cursor:project")],
                agents=[_agent("project-agent")],
            ),
            ScanResult(
                mcps=[
                    _mcp("shared", source="cursor:home-project"),
                    _mcp("extra-only", source="cursor:home-project"),
                ],
                skills=[_skill("ignored-extra-skill", "cursor:home-project")],
                hooks=[_hook("ignored-extra-hook", "cursor:home-project")],
                agents=[_agent("ignored-extra-agent")],
            ),
        ],
        hook_status="partial",
    )
    kiro = _adapter(
        home_result=ScanResult(
            mcps=[
                _mcp("shared", source="kiro:home"),
                _mcp("kiro-only", source="kiro:home", url="https://example.test/mcp", command=None),
            ]
        ),
        project_results=[ScanResult(), ScanResult()],
        hook_status="missing",
    )
    scan_env.get_all.return_value = {"cursor": cursor, "kiro": kiro}

    result = _invoke("-o", "json")

    assert result.exit_code == 0, result.exception
    payload = json.loads(result.output)
    assert list(payload) == ["harnesses", "mcps", "skills", "hooks", "agents"]
    assert payload["harnesses"] == [
        {"name": "cursor", "hooks": "partial"},
        {"name": "kiro", "hooks": "missing"},
    ]
    assert [item["name"] for item in payload["mcps"]] == [
        "extra-only",
        "home-only",
        "kiro-only",
        "project-only",
        "shared",
        "shared",
        "shared",
    ]
    shared = [item for item in payload["mcps"] if item["name"] == "shared"]
    assert [item["args"] for item in shared] == [["home"], [], ["project"]]
    assert [item["name"] for item in payload["skills"]] == [
        "home-skill",
        "ignored-extra-skill",
        "project-skill",
    ]
    assert [item["name"] for item in payload["hooks"]] == [
        "home-hook",
        "ignored-extra-hook",
        "project-hook",
    ]
    assert [item["name"] for item in payload["agents"]] == [
        "home-agent",
        "ignored-extra-agent",
        "project-agent",
    ]
    assert scan_env.spinner_calls == []
    assert scan_env.tables == []
    scan_env.console_print.assert_not_called()
    scan_env.config_load.assert_not_called()


def test_unsupported_scan_and_hook_capabilities_become_empty_results(scan_env, tmp_path: Path) -> None:
    root = tmp_path / "unsupported-root"
    root.mkdir()
    adapter = _adapter(resolved_home=root)
    adapter.scan_home.side_effect = NotSupportedError("unsupported", "scan_home")
    adapter.scan_project.side_effect = NotSupportedError("unsupported", "scan_project")
    adapter.detect_hooks.side_effect = NotSupportedError("unsupported", "detect_hooks")
    scan_env.get_all.return_value = {"unsupported": adapter}

    result = _invoke("-o", "json")

    assert result.exit_code == 0, result.exception
    assert json.loads(result.output) == {
        "harnesses": [{"name": "unsupported", "hooks": "n/a"}],
        "mcps": [],
        "skills": [],
        "hooks": [],
        "agents": [],
    }
    adapter.scan_home.assert_called_once_with(None)
    assert adapter.scan_project.call_args_list == [call(scan_env.project), call(scan_env.home)]
    adapter.detect_hooks.assert_called_once_with(root)


def test_component_tables_apply_display_normalization_without_legacy_shim_columns(scan_env, tmp_path: Path) -> None:
    root = tmp_path / "component-root"
    root.mkdir()
    long_description = "d" * 75
    adapter = _adapter(
        resolved_home=root,
        home_result=ScanResult(
            mcps=[_mcp("local", source="home", args=["-y", "server"])],
            skills=[_skill("z-one", "z-plugin"), _skill("a-one", "a-plugin")],
        ),
        project_results=[
            ScanResult(
                mcps=[_mcp("remote", source="project", command=None, url="https://example.test/mcp")],
                skills=[_skill("a-two", "a-plugin")],
                hooks=[_hook("stop-hook", "project", "Stop")],
                agents=[
                    _agent("default-model", model="", description=long_description),
                    _agent("named-model", model="model-b"),
                ],
            ),
            ScanResult(),
        ],
    )
    scan_env.get_all.return_value = {"custom": adapter}

    result = _invoke()

    assert result.exit_code == 0, result.exception
    tables = {table.title: table for table in scan_env.tables}
    assert list(tables) == [
        "harnesses Detected",
        "MCP Servers (2)",
        "Skills (3)",
        "Hooks (1)",
        "Agents (2)",
    ]
    status = tables["harnesses Detected"]
    assert [name for name, _options in status.columns] == ["harness", "Hooks"]
    assert status.rows == [("custom", "[green]installed[/green]")]

    mcps = tables["MCP Servers (2)"]
    assert [name for name, _options in mcps.columns] == ["Name", "Command/URL", "Source"]
    assert mcps.rows == [
        ("local", "npx -y server", "home"),
        ("remote", "https://example.test/mcp", "project"),
    ]
    assert tables["Skills (3)"].rows == [("a-plugin", "2"), ("z-plugin", "1")]
    assert tables["Hooks (1)"].rows == [("stop-hook", "Stop", "project")]
    assert tables["Agents (2)"].rows == [
        ("default-model", "-", long_description[:60]),
        ("named-model", "model-b", "Description for named-model"),
    ]
    assert scan_env.console_print.call_args_list == [call(table) for table in scan_env.tables]
    scan_env.save_aliases.assert_not_called()
    scan_env.save_last_results.assert_not_called()


def test_hook_status_styles_and_missing_hook_suggestion(scan_env, tmp_path: Path) -> None:
    adapters = {}
    for name, status in (
        ("installed", "installed"),
        ("partial", "partial"),
        ("missing", "missing"),
        ("unsupported", "installed"),
    ):
        root = tmp_path / name
        root.mkdir()
        adapters[name] = _adapter(resolved_home=root, hook_status=status)
    adapters["unsupported"].detect_hooks.side_effect = NotSupportedError("unsupported", "detect_hooks")
    scan_env.get_all.return_value = adapters

    result = _invoke()

    assert result.exit_code == 0, result.exception
    assert len(scan_env.tables) == 1
    table = scan_env.tables[0]
    assert table.rows == [
        ("installed", "[green]installed[/green]"),
        ("missing", "[red]missing[/red]"),
        ("partial", "[yellow]partial[/yellow]"),
        ("unsupported", "[red]n/a[/red]"),
    ]
    assert any("doctor patch" in str(args) for args in scan_env.rprint.call_args_list)


def test_authenticated_registry_results_hide_registered_components_and_cap_rows(scan_env, tmp_path: Path) -> None:
    root = tmp_path / "registry-root"
    root.mkdir()
    unregistered_mcps = [_mcp(f"unregistered-{index:02}", source="home") for index in range(31)]
    adapter = _adapter(
        resolved_home=root,
        home_result=ScanResult(
            mcps=[_mcp("registered-mcp", source="home"), *unregistered_mcps],
            skills=[_skill("registered-skill", "home"), _skill("missing-skill", "home")],
            agents=[_agent("registered-agent"), _agent("missing-agent")],
        ),
    )
    scan_env.get_all.return_value = {"custom": adapter}
    scan_env.config_load.return_value = {
        "access_token": "token-value",
        "server_url": "https://registry.example///",
    }
    scan_env.registered_only.return_value = True

    responses = {
        "mcp": [{"name": "registered-mcp"}, {}],
        "skills": [{"name": "registered-skill"}],
        "agents": [{"name": "registered-agent"}],
    }

    def registry_response(url: str, **_kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        return SimpleNamespace(status_code=200, json=Mock(return_value=responses[endpoint]))

    scan_env.http_get.side_effect = registry_response

    result = _invoke()

    assert result.exit_code == 0, result.exception
    headers = {"Authorization": "Bearer token-value"}
    assert scan_env.http_get.call_args_list == [
        call("https://registry.example/api/v1/mcp", headers=headers, timeout=5),
        call("https://registry.example/api/v1/skills", headers=headers, timeout=5),
        call("https://registry.example/api/v1/agents", headers=headers, timeout=5),
    ]
    unregistered = next(table for table in scan_env.tables if table.title == "Unregistered Components (33)")
    assert len(unregistered.rows) == 31
    assert unregistered.rows[0] == ("mcp", "unregistered-00")
    assert unregistered.rows[-2] == ("mcp", "unregistered-29")
    assert unregistered.rows[-1] == ("...", "and 3 more")
    assert all("registered-mcp" not in row for row in unregistered.rows)
    scan_env.registered_only.assert_called_once_with()
    assert any("Registered-agents-only mode is ON" in str(args) for args in scan_env.rprint.call_args_list)


def test_all_registered_components_skip_the_unregistered_table(scan_env, tmp_path: Path) -> None:
    root = tmp_path / "all-registered-root"
    root.mkdir()
    adapter = _adapter(
        resolved_home=root,
        home_result=ScanResult(
            mcps=[_mcp("known-mcp", source="home")],
            skills=[_skill("known-skill", "home")],
            agents=[_agent("known-agent")],
        ),
    )
    scan_env.get_all.return_value = {"custom": adapter}
    scan_env.config_load.return_value = {"access_token": "token", "server_url": "https://registry.example"}
    payloads = [[{"name": "known-mcp"}], [{"name": "known-skill"}], [{"name": "known-agent"}]]
    scan_env.http_get.side_effect = [
        SimpleNamespace(status_code=200, json=Mock(return_value=payload)) for payload in payloads
    ]

    result = _invoke()

    assert result.exit_code == 0, result.exception
    assert not any(table.title.startswith("Unregistered Components") for table in scan_env.tables)
    scan_env.registered_only.assert_not_called()


@pytest.mark.parametrize("response_mode", ["exception", "error-status"])
def test_registry_request_failures_leave_registration_state_unavailable(
    scan_env, tmp_path: Path, response_mode: str
) -> None:
    root = tmp_path / "registry-failure-root"
    root.mkdir()
    adapter = _adapter(
        resolved_home=root,
        home_result=ScanResult(
            mcps=[_mcp("local-mcp", source="home")],
            skills=[_skill("local-skill", "home")],
            agents=[_agent("local-agent")],
        ),
    )
    scan_env.get_all.return_value = {"custom": adapter}
    scan_env.config_load.return_value = {"access_token": "token", "server_url": "https://registry.example"}
    if response_mode == "exception":
        scan_env.http_get.side_effect = [
            OSError("mcp unavailable"),
            OSError("skills unavailable"),
            OSError("agents unavailable"),
        ]
    else:
        scan_env.http_get.side_effect = [SimpleNamespace(status_code=503)] * 3

    result = _invoke()

    assert result.exit_code == 0, result.exception
    assert not any(table.title.startswith("Unregistered Components") for table in scan_env.tables)


def test_optional_config_failure_does_not_prevent_local_results(scan_env, tmp_path: Path) -> None:
    root = tmp_path / "config-failure-root"
    root.mkdir()
    adapter = _adapter(resolved_home=root, home_result=ScanResult(mcps=[_mcp("local", source="home")]))
    scan_env.get_all.return_value = {"custom": adapter}
    scan_env.config_load.side_effect = ValueError("invalid config")

    result = _invoke()

    assert result.exit_code == 0, result.exception
    assert any(table.title == "MCP Servers (1)" for table in scan_env.tables)
    scan_env.http_get.assert_not_called()


@pytest.mark.parametrize("method", ["resolve_home_dir", "scan_home", "scan_project", "detect_hooks"])
def test_adapter_failures_surface_to_the_cli(scan_env, tmp_path: Path, method: str) -> None:
    root = tmp_path / f"failure-{method}"
    root.mkdir()
    adapter = _adapter(resolved_home=root)
    error = RuntimeError(f"{method} failed")
    getattr(adapter, method).side_effect = error
    scan_env.get_all.return_value = {"custom": adapter}

    result = _invoke()

    assert result.exit_code == 1
    assert result.exception is error


def test_filesystem_failure_while_checking_a_harness_root_surfaces(scan_env) -> None:
    error = PermissionError("cannot inspect harness root")
    adapter = _adapter(resolved_home=UnreadableRoot(error))
    scan_env.get_all.return_value = {"custom": adapter}

    result = _invoke()

    assert result.exit_code == 1
    assert result.exception is error
    adapter.scan_home.assert_not_called()
