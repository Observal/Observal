# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Bounded discovery of top-level pipx applications."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
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
    sorted_children,
)

if TYPE_CHECKING:
    from observal_cli.discovery.models import ProviderResult
    from observal_cli.discovery.providers._utils import CommandRunner


def _pipx_home(environment: Mapping[str, str], home: Path) -> Path:
    configured = environment.get("PIPX_HOME")
    return Path(configured).expanduser() if configured else home / ".local" / "share" / "pipx"


def _add_tool(
    context: ProviderContext,
    *,
    package_name: str,
    version: str | None,
    apps: tuple[str, ...],
    source: Path | None,
) -> None:
    binaries: tuple[str | None, ...] = apps or (None,)
    for binary in binaries:
        context.add(
            DiscoveryEvidence(
                component=None,
                provider=ProviderKind.PIPX,
                scope=DiscoveryScope.GLOBAL,
                source_path=source,
                display_path=context.display_path(source) if source is not None else "pipx:list",
                package_ecosystem=PackageEcosystem.PYPI,
                package_name=package_name,
                package_version=version,
                launch=SanitizedLaunch(
                    kind=LaunchKind.PIPX,
                    package=package_name,
                    binary=binary,
                    version=version,
                ),
            )
        )


def _from_json(data: object, root: Path, context: ProviderContext) -> bool:
    if not isinstance(data, Mapping) or not isinstance(data.get("venvs"), Mapping):
        return False
    venvs = data["venvs"]
    for key in sorted(venvs, key=lambda value: str(value).casefold()):
        if not context.start_record():
            break
        raw_info = venvs[key]
        if not isinstance(key, str) or not isinstance(raw_info, Mapping):
            context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "pipx tool metadata is malformed")
            continue
        metadata = raw_info.get("metadata")
        main = metadata.get("main_package") if isinstance(metadata, Mapping) else None
        if not isinstance(main, Mapping):
            main = raw_info.get("main_package")
        if not isinstance(main, Mapping):
            context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "pipx main package metadata is missing")
            continue
        raw_name = main.get("package") or main.get("package_name") or key
        if not isinstance(raw_name, str) or not raw_name.strip():
            context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "pipx package name is invalid")
            continue
        name = safe_python_package_name(raw_name)
        if name is None:
            context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "pipx package name is invalid")
            continue
        raw_version = main.get("package_version") or main.get("version")
        version = safe_version(raw_version)
        if raw_version is not None and version is None:
            context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "pipx package version is invalid")
        raw_apps = main.get("apps")
        raw_app_names = raw_apps if isinstance(raw_apps, list) else []
        apps = tuple(
            sorted(
                {app for value in raw_app_names if (app := safe_executable_name(value)) is not None},
                key=str.casefold,
            )
        )
        if len(apps) != len(raw_app_names):
            context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "pipx application metadata is invalid")

        environment = contained_directory(root, root / "venvs" / key, context)
        if environment is None:
            environment = contained_directory(root, root / key, context)
        distribution = inspect_distribution(environment, name, context) if environment is not None else None
        if distribution is not None:
            version = distribution.version or version
            apps = tuple(sorted(set(apps).union(distribution.apps), key=str.casefold))
        source = distribution.metadata_path if distribution is not None else None
        _add_tool(context, package_name=name, version=version, apps=apps, source=source)
    return True


def _from_filesystem(root: Path, context: ProviderContext) -> None:
    venv_root = contained_directory(root, root / "venvs", context)
    if venv_root is None:
        # Some installations return or configure the venv directory itself.
        venv_root = root
    for environment_path in sorted_children(venv_root, context):
        if not context.start_record():
            break
        environment = contained_directory(venv_root, environment_path, context)
        if environment is None:
            continue
        name = safe_python_package_name(environment.name)
        if name is None:
            context.diagnostic(
                DiagnosticCode.METADATA_MALFORMED,
                "pipx environment name is invalid",
                source=environment,
            )
            continue
        distribution = inspect_distribution(environment, name, context)
        if distribution is None:
            context.diagnostic(
                DiagnosticCode.METADATA_MALFORMED,
                "pipx environment has no matching top-level distribution metadata",
                source=environment,
            )
            continue
        _add_tool(
            context,
            package_name=distribution.name,
            version=distribution.version,
            apps=distribution.apps,
            source=distribution.metadata_path,
        )


def discover_pipx(
    *,
    runner: CommandRunner | None = None,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    clock=None,
    max_records: int | None = None,
) -> ProviderResult:
    """Discover pipx applications, falling back to bounded filesystem metadata."""

    effective_home = home or Path.home()
    environment = os.environ if environment is None else environment
    options: dict[str, Any] = {"provider": ProviderKind.PIPX.value, "home": effective_home}
    if runner is not None:
        options["runner"] = runner
    if clock is not None:
        options["clock"] = clock
    if max_records is not None:
        options["max_records"] = max_records
    context = ProviderContext(**options)
    root = _pipx_home(environment, effective_home)
    try:
        resolved_root = root.resolve(strict=True)
    except OSError:
        resolved_root = root

    listing = context.command(("pipx", "list", "--json"))
    parsed = False
    if listing is not None:
        try:
            parsed = _from_json(json.loads(listing), resolved_root, context)
            if not parsed:
                context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "pipx JSON output has an unsupported schema")
        except json.JSONDecodeError:
            context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "pipx JSON output is malformed")
    if not parsed:
        try:
            fallback_root = resolved_root.resolve(strict=True)
        except OSError:
            fallback_root = None
        if fallback_root is not None and fallback_root.is_dir():
            _from_filesystem(fallback_root, context)

    context.result.evidence.sort(
        key=lambda item: (item.package_name or "", item.launch.binary if item.launch and item.launch.binary else "")
    )
    context.result.diagnostics.sort(key=lambda item: (item.source or "", item.code.value, item.message))
    return context.result
