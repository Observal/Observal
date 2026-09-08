# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Read-only legacy and rich discovery collection pipelines.

The default scan retains legacy adapter behavior. Opt-in discovery combines
bounded rich adapter evidence, package providers, local matching, and exact
Registry classification without mutating local state.
"""

from __future__ import annotations

import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from observal_cli.discovery.bounded_walk import AggregateDiscoveryBudget, discovery_budget
from observal_cli.discovery.matcher import apply_local_match
from observal_cli.discovery.models import (
    AdapterDiscoveryResult,
    DiagnosticCode,
    DiagnosticSeverity,
    DiscoveryCandidate,
    DiscoveryDiagnostic,
    DiscoveryEvidence,
)
from observal_cli.discovery.normalize import build_candidates, normalize_launch
from observal_cli.discovery.providers import discover_npm, discover_pipx, discover_uv
from observal_cli.discovery.redact import make_diagnostic
from observal_cli.discovery.registry import classify_registry_candidates
from observal_cli.harness import (
    DiscoveredAgent,
    DiscoveredHook,
    DiscoveredMcp,
    DiscoveredSkill,
    NotSupportedError,
    ScanResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable, ContextManager, Mapping

    from observal_cli.harness import HarnessAdapter


HARNESS_HOME_DIRS: dict[str, str] = {
    "claude-code": "~/.claude",
    "kiro": "~/.kiro",
    "codex": "~/.codex",
    "copilot": "~/.vscode",
    "copilot-cli": "~/.copilot",
    "opencode": "~/.config/opencode",
    "antigravity": "~/.gemini",
    "cursor": "~/.cursor",
    "pi": "~/.pi/agent",
}


class ScanContextFactory(Protocol):
    def __call__(self, message: str) -> ContextManager[None]: ...


@dataclass(frozen=True)
class HarnessStatus:
    name: str
    hooks: str


@dataclass
class LegacyScanCollection:
    harnesses: list[HarnessStatus] = field(default_factory=list)
    mcps: list[DiscoveredMcp] = field(default_factory=list)
    skills: list[DiscoveredSkill] = field(default_factory=list)
    hooks: list[DiscoveredHook] = field(default_factory=list)
    agents: list[DiscoveredAgent] = field(default_factory=list)

    @property
    def component_count(self) -> int:
        return len(self.mcps) + len(self.skills) + len(self.hooks) + len(self.agents)

    @property
    def has_findings(self) -> bool:
        return bool(self.harnesses or self.component_count)


@dataclass
class DiscoveryScanCollection(LegacyScanCollection):
    candidates: list[DiscoveryCandidate] = field(default_factory=list)
    diagnostics: list[DiscoveryDiagnostic] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return bool(super().has_findings or self.candidates)


def _empty_result() -> ScanResult:
    return ScanResult()


def _scan_home(adapter: HarnessAdapter, argument: Path | None) -> ScanResult:
    try:
        return adapter.scan_home(argument)
    except NotSupportedError:
        return _empty_result()


def _scan_project(adapter: HarnessAdapter, project_dir: Path) -> ScanResult:
    try:
        return adapter.scan_project(project_dir)
    except NotSupportedError:
        return _empty_result()


def _mcp_identity(mcp: DiscoveredMcp) -> tuple[object, ...]:
    """Deduplicate only equivalent launches with the same local name."""

    normalized = normalize_launch(command=mcp.command, arguments=mcp.args, url=mcp.url)
    launch_identity: tuple[object, ...]
    if normalized.launch_fingerprint is not None:
        launch_identity = ("fingerprint", normalized.launch_fingerprint)
    else:
        launch_identity = (
            "structured",
            mcp.command or "",
            tuple(mcp.args),
            mcp.url or "",
        )
    return (mcp.name.casefold(), *launch_identity)


def _merge_result(
    collection: LegacyScanCollection,
    result: ScanResult,
    seen_mcps: set[tuple[object, ...]],
) -> None:
    for mcp in result.mcps:
        identity = _mcp_identity(mcp)
        if identity not in seen_mcps:
            collection.mcps.append(mcp)
            seen_mcps.add(identity)
    collection.skills.extend(result.skills)
    collection.hooks.extend(result.hooks)
    collection.agents.extend(result.agents)


def _sort_key(component: object) -> tuple[str, str, str]:
    name = str(getattr(component, "name", "")).casefold()
    source = str(getattr(component, "source", getattr(component, "source_file", "")))
    return name, source, source.replace("\\", "/")


def collect_harness_discovery(
    adapters: Mapping[str, HarnessAdapter],
    *,
    home: Path,
    project_dir: Path,
    total_deadline_seconds: float = 30.0,
    clock: Callable[[], float] = time.monotonic,
    budget: AggregateDiscoveryBudget | None = None,
) -> AdapterDiscoveryResult:
    """Collect rich harness evidence under shared aggregate and time limits."""
    combined = AdapterDiscoveryResult()
    budget = budget or AggregateDiscoveryBudget()
    total_deadline = clock() + total_deadline_seconds
    limit_codes = {
        DiagnosticCode.APPROVED_ROOT_LIMIT_REACHED,
        DiagnosticCode.COLLECTION_FILE_LIMIT_REACHED,
        DiagnosticCode.EVIDENCE_LIMIT_REACHED,
    }

    def reached_aggregate_limit() -> bool:
        limits = (
            (
                budget.roots >= budget.max_roots,
                DiagnosticCode.APPROVED_ROOT_LIMIT_REACHED,
                "approved discovery root limit reached",
            ),
            (
                budget.files >= budget.max_files,
                DiagnosticCode.COLLECTION_FILE_LIMIT_REACHED,
                "aggregate discovery file limit reached",
            ),
            (
                budget.evidence >= budget.max_evidence,
                DiagnosticCode.EVIDENCE_LIMIT_REACHED,
                "aggregate discovery evidence limit reached",
            ),
        )
        for reached, code, message in limits:
            if not reached:
                continue
            if code not in budget.emitted_limits and budget.diagnostics < budget.max_diagnostics:
                budget.emitted_limits.add(code)
                budget.diagnostics += 1
                combined.diagnostics.append(
                    make_diagnostic(
                        code=code,
                        severity=DiagnosticSeverity.WARNING,
                        provider="harness",
                        source=None,
                        message=message,
                    )
                )
            return True
        return bool(budget.emitted_limits.intersection(limit_codes))

    for harness_name in sorted(adapters):
        adapter = adapters[harness_name]
        if clock() > total_deadline:
            if budget.diagnostics < budget.max_diagnostics:
                combined.diagnostics.append(
                    make_diagnostic(
                        code=DiagnosticCode.ADAPTER_DEADLINE_EXCEEDED,
                        severity=DiagnosticSeverity.WARNING,
                        provider="harness",
                        source=None,
                        message="total harness discovery deadline exceeded",
                    )
                )
                budget.diagnostics += 1
            break
        adapter_deadline = min(total_deadline, clock() + 10)
        with discovery_budget(budget, deadline=adapter_deadline):
            discovery_calls = (
                (adapter.discover_home, home),
                (adapter.discover_project, project_dir),
            )
            for discover, root in discovery_calls:
                discovered = discover(root)
                combined.evidence.extend(discovered.evidence)
                combined.diagnostics.extend(discovered.diagnostics)
                if reached_aggregate_limit():
                    break
        if reached_aggregate_limit():
            break

    combined.evidence.sort(
        key=lambda item: (
            item.harness or "",
            item.scope.value,
            item.display_path or "",
            str(getattr(item.component, "name", "")).casefold(),
        )
    )
    combined.diagnostics.sort(key=lambda item: (item.provider, item.source or "", item.code.value, item.message))
    return combined


def _harness_statuses(
    adapters: Mapping[str, HarnessAdapter],
    *,
    home: Path,
) -> list[HarnessStatus]:
    statuses: list[HarnessStatus] = []
    for harness_name in sorted(adapters):
        adapter = adapters[harness_name]
        resolved_home = adapter.resolve_home_dir()
        if resolved_home is not None:
            home_dir = resolved_home
        else:
            configured_home = HARNESS_HOME_DIRS.get(harness_name, "")
            home_dir = Path(configured_home.replace("~", str(home))) if configured_home else None
        if home_dir is not None and not home_dir.is_dir():
            continue
        try:
            config_dir = home_dir or (home / ".config" / harness_name)
            hooks = adapter.detect_hooks(config_dir)
        except NotSupportedError:
            hooks = "n/a"
        statuses.append(HarnessStatus(harness_name, hooks))
    return statuses


def _legacy_from_evidence(
    evidence: list[DiscoveryEvidence],
    harnesses: list[HarnessStatus],
) -> LegacyScanCollection:
    collection = LegacyScanCollection(harnesses=list(harnesses))
    seen_mcps: set[tuple[object, ...]] = set()
    result = ScanResult()
    for item in evidence:
        component = item.component
        if isinstance(component, DiscoveredMcp):
            result.mcps.append(component)
        elif isinstance(component, DiscoveredSkill):
            result.skills.append(component)
        elif isinstance(component, DiscoveredHook):
            result.hooks.append(component)
        elif isinstance(component, DiscoveredAgent):
            result.agents.append(component)
    _merge_result(collection, result, seen_mcps)
    collection.mcps.sort(key=_sort_key)
    collection.skills.sort(key=_sort_key)
    collection.hooks.sort(key=_sort_key)
    collection.agents.sort(key=_sort_key)
    return collection


def collect_discovery_scan(
    adapters: Mapping[str, HarnessAdapter],
    *,
    home: Path,
    project_dir: Path,
    harness_filtered: bool = False,
) -> DiscoveryScanCollection:
    """Run the complete read-only discovery and classification pipeline."""

    from observal_cli import config
    from observal_cli.errors import CliError
    from observal_cli.lockfile import read_registry_snapshot

    harness_result = collect_harness_discovery(adapters, home=home, project_dir=project_dir)
    npm_result = discover_npm(home=home)
    pipx_result = discover_pipx(home=home)
    existing = [*harness_result.evidence, *npm_result.evidence, *pipx_result.evidence]
    uv_result = discover_uv(home=home, existing_evidence=existing)
    all_evidence = [*existing, *uv_result.evidence]
    candidates = build_candidates(all_evidence, suppress_package_only=harness_filtered)

    configuration: dict[str, object] | None = None
    try:
        configuration = config.load()
    except CliError:
        pass
    registry = read_registry_snapshot(str(configuration.get("server_url") or "") if configuration else None)
    for candidate in candidates:
        apply_local_match(candidate, registry, project_directory=project_dir)

    diagnostics = [
        *harness_result.diagnostics,
        *npm_result.diagnostics,
        *pipx_result.diagnostics,
        *uv_result.diagnostics,
    ]
    diagnostics.extend(classify_registry_candidates(candidates, configuration=configuration))
    severity_order = {"error": 0, "warning": 1, "info": 2}
    diagnostics.sort(
        key=lambda item: (severity_order[item.severity.value], item.provider, item.code.value, item.source or "")
    )

    legacy = _legacy_from_evidence(harness_result.evidence, _harness_statuses(adapters, home=home))
    return DiscoveryScanCollection(
        harnesses=legacy.harnesses,
        mcps=legacy.mcps,
        skills=legacy.skills,
        hooks=legacy.hooks,
        agents=legacy.agents,
        candidates=candidates,
        diagnostics=diagnostics,
    )


def collect_legacy_scan(
    adapters: Mapping[str, HarnessAdapter],
    *,
    home: Path,
    project_dir: Path,
    scan_context: ScanContextFactory | None = None,
) -> LegacyScanCollection:
    """Collect default-scan results without suppressing project scopes.

    A missing static harness home suppresses only that home scan and status;
    the current project and the historical home-as-project scope are still
    scanned independently.
    """

    context_factory: Callable[[str], ContextManager[None]] = scan_context or (lambda _message: nullcontext())
    collection = LegacyScanCollection()
    seen_mcps: set[tuple[object, ...]] = set()

    for harness_name in sorted(adapters):
        adapter = adapters[harness_name]
        resolved_home = adapter.resolve_home_dir()
        if resolved_home is not None:
            home_dir = resolved_home
            home_label = str(resolved_home)
            home_argument = None
        else:
            configured_home = HARNESS_HOME_DIRS.get(harness_name, "")
            home_label = configured_home or harness_name
            home_dir = Path(configured_home.replace("~", str(home))) if configured_home else None
            home_argument = home

        scan_home = home_dir is None or home_dir.is_dir()
        if scan_home:
            with context_factory(f"Scanning {home_label}..."):
                _merge_result(collection, _scan_home(adapter, home_argument), seen_mcps)
                _merge_result(collection, _scan_project(adapter, project_dir), seen_mcps)

            try:
                config_dir = home_dir or (home / ".config" / harness_name)
                hook_status = adapter.detect_hooks(config_dir)
            except NotSupportedError:
                hook_status = "n/a"
            collection.harnesses.append(HarnessStatus(harness_name, hook_status))
        else:
            _merge_result(collection, _scan_project(adapter, project_dir), seen_mcps)

        if project_dir != home:
            _merge_result(collection, _scan_project(adapter, home), seen_mcps)

    collection.harnesses.sort(key=lambda item: item.name)
    collection.mcps.sort(key=_sort_key)
    collection.skills.sort(key=_sort_key)
    collection.hooks.sort(key=_sort_key)
    collection.agents.sort(key=_sort_key)
    return collection
