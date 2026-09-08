# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from observal_cli.discovery.adapter_support import RichAdapterScanner
from observal_cli.discovery.bounded_walk import AggregateDiscoveryBudget
from observal_cli.discovery.collector import collect_discovery_scan, collect_harness_discovery, collect_legacy_scan
from observal_cli.discovery.models import (
    AdapterDiscoveryResult,
    DiagnosticCode,
    DiscoveryEvidence,
    DiscoveryScope,
    LaunchKind,
    PackageEcosystem,
    ProviderKind,
    ProviderResult,
    SanitizedLaunch,
    TrackingStatus,
)
from observal_cli.harness import (
    DiscoveredAgent,
    DiscoveredHook,
    DiscoveredMcp,
    DiscoveredSkill,
    NotSupportedError,
    ScanResult,
)


def _mcp(name: str, argument: str, source: str) -> DiscoveredMcp:
    return DiscoveredMcp(name, "npx", ["server", argument], None, "", source)


def _adapter(*, home: ScanResult | None = None, projects: list[ScanResult] | None = None, status: str = "installed"):
    project = Mock(side_effect=projects) if projects is not None else Mock(return_value=ScanResult())
    return SimpleNamespace(
        resolve_home_dir=Mock(return_value=None),
        scan_home=Mock(return_value=home or ScanResult()),
        scan_project=project,
        detect_hooks=Mock(return_value=status),
    )


def test_missing_home_still_scans_current_project(tmp_path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    current = ScanResult(mcps=[_mcp("project-server", "--project", "project")])
    adapter = _adapter(projects=[current, ScanResult()])

    result = collect_legacy_scan({"cursor": adapter}, home=home, project_dir=project)

    adapter.scan_home.assert_not_called()
    adapter.scan_project.assert_called_once_with(project)
    assert [item.name for item in result.mcps] == ["project-server"]
    assert result.has_findings


def test_home_as_project_preserves_legacy_mcp_only_behavior(tmp_path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / ".cursor").mkdir()
    secondary = ScanResult(
        mcps=[_mcp("secondary-mcp", "--home", "secondary")],
        skills=[DiscoveredSkill("secondary-skill", "", "secondary")],
        hooks=[DiscoveredHook("secondary-hook", "Stop", "command", {}, "", "secondary")],
        agents=[DiscoveredAgent("secondary-agent", "", "", "", "AGENTS.md")],
    )
    adapter = _adapter(projects=[ScanResult(), secondary])

    result = collect_legacy_scan({"cursor": adapter}, home=home, project_dir=project)

    assert [item.name for item in result.mcps] == ["secondary-mcp"]
    assert result.skills == []
    assert result.hooks == []
    assert result.agents == []


def test_legacy_scan_deduplicates_mcps_by_name(tmp_path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / ".cursor").mkdir()
    first = _mcp("shared", "--first", "home")
    duplicate = _mcp("shared", "--first", "project")
    distinct = _mcp("shared", "--second", "project")
    adapter = _adapter(home=ScanResult(mcps=[first]), projects=[ScanResult(mcps=[duplicate, distinct]), ScanResult()])

    result = collect_legacy_scan({"cursor": adapter}, home=home, project_dir=project)

    assert [(item.name, item.args, item.source) for item in result.mcps] == [
        ("shared", ["server", "--first"], "home"),
    ]


def test_legacy_collection_preserves_adapter_order(tmp_path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = _adapter(home=ScanResult(skills=[DiscoveredSkill("zeta", "", "z-source")]), status="partial")
    second = _adapter(home=ScanResult(skills=[DiscoveredSkill("Alpha", "", "a-source")]), status="missing")
    first.resolve_home_dir.return_value = first_root
    second.resolve_home_dir.return_value = second_root

    result = collect_legacy_scan({"z-harness": first, "a-harness": second}, home=home, project_dir=project)

    assert [(item.name, item.hooks) for item in result.harnesses] == [
        ("z-harness", "partial"),
        ("a-harness", "missing"),
    ]
    assert [item.name for item in result.skills] == ["zeta", "Alpha"]


def test_rich_collection_shares_aggregate_limits_across_adapters(tmp_path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()

    class RichAdapter:
        def __init__(self, name: str) -> None:
            self.harness_name = name
            self.calls: list[str] = []

        def _discover(self, root, scope):
            self.calls.append(scope.value)
            scanner = RichAdapterScanner(harness=self.harness_name, scope=scope, root=root)
            scanner.add_component(DiscoveredAgent(self.harness_name, "", "", "prompt", str(root)), root)
            return scanner.finish()

        def discover_home(self, root):
            return self._discover(root, DiscoveryScope.USER)

        def discover_project(self, root):
            return self._discover(root, DiscoveryScope.PROJECT)

    first = RichAdapter("a")
    second = RichAdapter("b")
    result = collect_harness_discovery(
        {"b": second, "a": first},
        home=home,
        project_dir=project,
        budget=AggregateDiscoveryBudget(max_roots=1),
    )

    assert [item.harness for item in result.evidence] == ["a"]
    assert [item.code for item in result.diagnostics] == [DiagnosticCode.APPROVED_ROOT_LIMIT_REACHED]
    assert first.calls == ["user"]
    assert second.calls == []


def test_complete_discovery_pipeline_combines_providers_matches_lock_and_never_writes(tmp_path, monkeypatch) -> None:
    from observal_cli import config, lockfile

    home = tmp_path / "home"
    project = tmp_path / "project"
    harness_root = home / ".kiro"
    home.mkdir()
    project.mkdir()
    harness_root.mkdir()
    launch = SanitizedLaunch(kind=LaunchKind.NPM, package="server", binary="server")
    component = _mcp("server", "server", "kiro:project")
    harness_evidence = DiscoveryEvidence(
        component=component,
        provider=ProviderKind.HARNESS,
        scope=DiscoveryScope.PROJECT,
        harness="kiro",
        display_path="<project>/.kiro/settings/mcp.json",
        launch=launch,
    )
    package_evidence = DiscoveryEvidence(
        component=None,
        provider=ProviderKind.NPM,
        scope=DiscoveryScope.GLOBAL,
        package_ecosystem=PackageEcosystem.NPM,
        package_name="server",
        launch=launch,
    )
    adapter = SimpleNamespace(
        resolve_home_dir=Mock(return_value=harness_root),
        discover_home=Mock(return_value=AdapterDiscoveryResult()),
        discover_project=Mock(return_value=AdapterDiscoveryResult(evidence=[harness_evidence])),
        detect_hooks=Mock(return_value="installed"),
    )
    monkeypatch.setattr(config, "load", Mock(return_value={"server_url": "https://registry.test", "access_token": ""}))
    lock_path = tmp_path / "lockfile.json"
    lock_path.write_text(
        '{"lock_version":1,"harnesses":{"kiro":{"standalone":'
        '[{"type":"mcp","name":"server","scope":"project","directory":"' + str(project) + '"}]}}}'
    )
    before = lock_path.read_bytes()
    monkeypatch.setattr(lockfile, "LOCKFILE_PATH", lock_path)
    write = Mock(side_effect=AssertionError("discovery must not write"))
    monkeypatch.setattr(lockfile, "write_lockfile", write)
    monkeypatch.setattr(
        "observal_cli.discovery.collector.discover_npm", Mock(return_value=ProviderResult(evidence=[package_evidence]))
    )
    monkeypatch.setattr("observal_cli.discovery.collector.discover_pipx", Mock(return_value=ProviderResult()))
    discover_uv = Mock(return_value=ProviderResult())
    monkeypatch.setattr("observal_cli.discovery.collector.discover_uv", discover_uv)
    registry = Mock(return_value=[])
    monkeypatch.setattr("observal_cli.discovery.collector.classify_registry_candidates", registry)

    result = collect_discovery_scan({"kiro": adapter}, home=home, project_dir=project)

    assert result.has_findings
    assert [item.name for item in result.mcps] == ["server"]
    assert len(result.candidates) == 1
    assert result.candidates[0].tracking_status is TrackingStatus.TRACKED
    assert len(result.candidates[0].evidence) == 2
    assert [(item.name, item.hooks) for item in result.harnesses] == [("kiro", "installed")]
    discover_uv.assert_called_once_with(home=home)
    registry.assert_called_once_with(
        result.candidates, configuration={"server_url": "https://registry.test", "access_token": ""}
    )
    assert lock_path.read_bytes() == before
    write.assert_not_called()


def test_discovery_reports_malformed_lockfile_without_traceback(tmp_path, monkeypatch) -> None:
    from observal_cli import config, lockfile

    lock_path = tmp_path / "lockfile.json"
    lock_path.write_text("{broken")
    monkeypatch.setattr(lockfile, "LOCKFILE_PATH", lock_path)
    monkeypatch.setattr(config, "load", Mock(return_value={"server_url": "https://registry.test"}))
    monkeypatch.setattr("observal_cli.discovery.collector.discover_npm", Mock(return_value=ProviderResult()))
    monkeypatch.setattr("observal_cli.discovery.collector.discover_pipx", Mock(return_value=ProviderResult()))
    monkeypatch.setattr("observal_cli.discovery.collector.discover_uv", Mock(return_value=ProviderResult()))
    monkeypatch.setattr("observal_cli.discovery.collector.classify_registry_candidates", Mock(return_value=[]))

    result = collect_discovery_scan({}, home=tmp_path, project_dir=tmp_path)

    assert [(item.provider, item.code) for item in result.diagnostics] == [
        ("lockfile", DiagnosticCode.REGISTRY_UNAVAILABLE)
    ]


def test_discovery_reports_malformed_registry_url_without_traceback(tmp_path, monkeypatch) -> None:
    from observal_cli import config, lockfile

    lock_path = tmp_path / "lockfile.json"
    lock_path.write_text('{"lock_version": 2, "registries": {}}')
    monkeypatch.setattr(lockfile, "LOCKFILE_PATH", lock_path)
    monkeypatch.setattr(config, "load", Mock(return_value={"server_url": "https://registry.test:notaport"}))
    monkeypatch.setattr("observal_cli.discovery.collector.discover_npm", Mock(return_value=ProviderResult()))
    monkeypatch.setattr("observal_cli.discovery.collector.discover_pipx", Mock(return_value=ProviderResult()))
    monkeypatch.setattr("observal_cli.discovery.collector.discover_uv", Mock(return_value=ProviderResult()))
    classify = Mock(return_value=[])
    monkeypatch.setattr("observal_cli.discovery.collector.classify_registry_candidates", classify)

    result = collect_discovery_scan({}, home=tmp_path, project_dir=tmp_path)

    assert [(item.provider, item.code) for item in result.diagnostics] == [
        ("lockfile", DiagnosticCode.REGISTRY_UNAVAILABLE)
    ]
    classify.assert_called_once_with([], configuration={})


def test_harness_filtered_discovery_suppresses_unrelated_package_candidates(tmp_path, monkeypatch) -> None:
    from observal_cli import config, lockfile

    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    package = DiscoveryEvidence(
        component=None,
        provider=ProviderKind.NPM,
        scope=DiscoveryScope.GLOBAL,
        package_ecosystem=PackageEcosystem.NPM,
        package_name="unrelated",
        launch=SanitizedLaunch(kind=LaunchKind.NPM, package="unrelated", binary="unrelated"),
    )
    adapter = SimpleNamespace(
        resolve_home_dir=Mock(return_value=None),
        discover_home=Mock(return_value=AdapterDiscoveryResult()),
        discover_project=Mock(return_value=AdapterDiscoveryResult()),
        detect_hooks=Mock(return_value="missing"),
    )
    monkeypatch.setattr(config, "load", Mock(return_value={}))
    monkeypatch.setattr(lockfile, "LOCKFILE_PATH", tmp_path / "absent-lockfile.json")
    monkeypatch.setattr(
        "observal_cli.discovery.collector.discover_npm", Mock(return_value=ProviderResult(evidence=[package]))
    )
    monkeypatch.setattr("observal_cli.discovery.collector.discover_pipx", Mock(return_value=ProviderResult()))
    monkeypatch.setattr("observal_cli.discovery.collector.discover_uv", Mock(return_value=ProviderResult()))
    monkeypatch.setattr("observal_cli.discovery.collector.classify_registry_candidates", Mock(return_value=[]))

    result = collect_discovery_scan({"kiro": adapter}, home=home, project_dir=project, harness_filtered=True)

    assert result.candidates == []
    assert not result.has_findings


def test_unsupported_scopes_are_empty_without_hiding_detected_harness(tmp_path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    root = tmp_path / "root"
    home.mkdir()
    project.mkdir()
    root.mkdir()
    adapter = _adapter()
    adapter.resolve_home_dir.return_value = root
    adapter.scan_home.side_effect = NotSupportedError("custom", "scan_home")
    adapter.scan_project.side_effect = NotSupportedError("custom", "scan_project")
    adapter.detect_hooks.side_effect = NotSupportedError("custom", "detect_hooks")

    result = collect_legacy_scan({"custom": adapter}, home=home, project_dir=project)

    assert result.component_count == 0
    assert result.has_findings
    assert [(item.name, item.hooks) for item in result.harnesses] == [("custom", "n/a")]
