# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Bounded discovery of installed uv tools and their environment metadata."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from observal_cli.discovery.models import (
    DiagnosticCode,
    DiscoveryEvidence,
    DiscoveryScope,
    LaunchKind,
    PackageEcosystem,
    ProviderKind,
    SanitizedLaunch,
)
from observal_cli.discovery.providers._python import inspect_distribution
from observal_cli.discovery.providers._utils import (
    ProviderContext,
    contained_directory,
    safe_executable_name,
    safe_python_package_name,
    safe_version,
)

if TYPE_CHECKING:
    from observal_cli.discovery.models import ProviderResult
    from observal_cli.discovery.providers._utils import CommandRunner

_TOOL_LINE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s+v?(?P<version>\S+)$")
_APP_LINE = re.compile(r"^\s*-\s+(?P<app>\S+)\s*$")


def _parse_tool_list(output: str, context: ProviderContext) -> list[tuple[str, str | None, tuple[str, ...]]]:
    tools: list[tuple[str, str | None, list[str]]] = []
    accepting_apps = False
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        app_match = _APP_LINE.match(raw_line)
        if app_match:
            if not tools or not accepting_apps:
                context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "uv tool list contains an orphan application")
                continue
            app = safe_executable_name(app_match.group("app"))
            if app is None:
                context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "uv tool list contains an invalid application")
                continue
            tools[-1][2].append(app)
            continue
        tool_match = _TOOL_LINE.match(raw_line.strip())
        if tool_match:
            name = safe_python_package_name(tool_match.group("name"))
            version = safe_version(tool_match.group("version"))
            if name is None or version is None:
                accepting_apps = False
                context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "uv tool list contains invalid metadata")
                continue
            tools.append((name, version, []))
            accepting_apps = True
            continue
        accepting_apps = False
        context.diagnostic(
            DiagnosticCode.METADATA_MALFORMED,
            "uv tool list contains an unrecognized record",
            once=True,
        )
    return sorted(
        [(name, version, tuple(sorted(set(apps), key=str.casefold))) for name, version, apps in tools],
        key=lambda item: item[0],
    )


def _add_tool(
    context: ProviderContext,
    *,
    name: str,
    version: str | None,
    apps: tuple[str, ...],
    source: Path | None,
) -> None:
    for app in apps or (None,):
        context.add(
            DiscoveryEvidence(
                component=None,
                provider=ProviderKind.UV,
                scope=DiscoveryScope.GLOBAL,
                source_path=source,
                display_path=context.display_path(source) if source is not None else "uv:tool-list",
                package_ecosystem=PackageEcosystem.PYPI,
                package_name=name,
                package_version=version,
                launch=SanitizedLaunch(
                    kind=LaunchKind.UV,
                    package=name,
                    binary=app,
                    version=version,
                ),
            )
        )


def discover_uv(
    *,
    runner: CommandRunner | None = None,
    home: Path | None = None,
    clock=None,
    max_records: int | None = None,
) -> ProviderResult:
    """Discover installed uv tools and their environment metadata."""

    effective_home = home or Path.home()
    options: dict[str, Any] = {"provider": ProviderKind.UV.value, "home": effective_home}
    if runner is not None:
        options["runner"] = runner
    if clock is not None:
        options["clock"] = clock
    if max_records is not None:
        options["max_records"] = max_records
    context = ProviderContext(**options)
    root_output = context.command(("uv", "tool", "dir"))
    if root_output is None:
        return context.result
    root_lines = root_output.strip().splitlines()
    if len(root_lines) != 1 or not root_lines[0]:
        context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "uv returned an invalid tool root")
        return context.result
    root = Path(root_lines[0]).expanduser()
    try:
        root = root.resolve(strict=True)
    except OSError:
        context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "uv tool root is unavailable", source=root)
        return context.result
    if not root.is_dir():
        context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "uv tool root is not a directory", source=root)
        return context.result
    listing = context.command(("uv", "tool", "list"))
    if listing is None:
        return context.result

    for name, version, apps in _parse_tool_list(listing, context):
        if not context.start_record():
            break
        environment = contained_directory(root, root / name, context)
        if environment is None:
            environment = contained_directory(root, root / name.replace("-", "_"), context)
        distribution = inspect_distribution(environment, name, context) if environment is not None else None
        if distribution is not None:
            version = distribution.version or version
            apps = tuple(sorted(set(apps).union(distribution.apps), key=str.casefold))
        _add_tool(
            context,
            name=name,
            version=version,
            apps=apps,
            source=distribution.metadata_path if distribution is not None else None,
        )

    context.result.evidence.sort(
        key=lambda item: (
            item.package_name or "",
            item.launch.binary if item.launch and item.launch.binary else "",
            item.display_path or "",
        )
    )
    context.result.diagnostics.sort(key=lambda item: (item.source or "", item.code.value, item.message))
    return context.result
