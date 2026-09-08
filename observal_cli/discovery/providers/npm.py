# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Bounded discovery of globally installed npm packages."""

from __future__ import annotations

import json
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
from observal_cli.discovery.normalize import split_npm_package_spec
from observal_cli.discovery.providers._utils import (
    ProviderContext,
    contained_directory,
    safe_executable_name,
    safe_version,
    sorted_children,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from observal_cli.discovery.models import ProviderResult
    from observal_cli.discovery.providers._utils import CommandRunner


def _package_directories(root: Path, context: ProviderContext) -> Iterator[Path]:
    for entry in sorted_children(root, context):
        if entry.name.startswith("@"):
            scope = contained_directory(root, entry, context)
            if scope is None:
                continue
            for scoped_entry in sorted_children(scope, context):
                if not context.start_record():
                    return
                if contained_directory(root, scoped_entry, context) is not None:
                    yield scoped_entry
        else:
            if not context.start_record():
                return
            if contained_directory(root, entry, context) is not None:
                yield entry


def _contained_bin(package_dir: Path, value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        (package_dir / value).resolve(strict=False).relative_to(package_dir.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _binaries(
    package_name: str,
    value: Any,
    context: ProviderContext,
    source: Path,
    package_dir: Path,
) -> tuple[str | None, ...]:
    if value is None:
        return (None,)
    if isinstance(value, str):
        binary = safe_executable_name(package_name.rsplit("/", 1)[-1])
        if binary is not None and _contained_bin(package_dir, value):
            return (binary,)
    elif isinstance(value, dict):
        binaries = tuple(
            sorted(
                (
                    binary
                    for name, target in value.items()
                    if (binary := safe_executable_name(name)) is not None and _contained_bin(package_dir, target)
                ),
                key=str.casefold,
            )
        )
        if len(binaries) == len(value):
            return binaries or (None,)
    context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "npm package bin metadata is malformed", source=source)
    return (None,)


def discover_npm(
    *,
    runner: CommandRunner | None = None,
    home: Path | None = None,
    clock=None,
    max_records: int | None = None,
) -> ProviderResult:
    """Return top-level global npm package evidence without walking dependencies."""

    options: dict[str, Any] = {"provider": ProviderKind.NPM.value, "home": home}
    if runner is not None:
        options["runner"] = runner
    if clock is not None:
        options["clock"] = clock
    if max_records is not None:
        options["max_records"] = max_records
    context = ProviderContext(**options)
    root_output = context.command(("npm", "root", "--global"))
    if root_output is None:
        return context.result
    root_value = root_output.strip().splitlines()
    if len(root_value) != 1 or not root_value[0]:
        context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "npm returned an invalid global package root")
        return context.result
    root = Path(root_value[0]).expanduser()
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "npm global package root is unavailable", source=root)
        return context.result
    if not root.is_dir():
        context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "npm global package root is not a directory", source=root)
        return context.result

    for package_dir in _package_directories(root, context):
        metadata_path = package_dir / "package.json"
        raw = context.read_metadata(root, metadata_path)
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError):
            context.diagnostic(
                DiagnosticCode.METADATA_MALFORMED, "npm package metadata is malformed", source=metadata_path
            )
            continue
        if not isinstance(data, Mapping):
            context.diagnostic(
                DiagnosticCode.METADATA_MALFORMED, "npm package metadata must be an object", source=metadata_path
            )
            continue
        name = data.get("name")
        version = data.get("version")
        if not isinstance(name, str) or split_npm_package_spec(name) is None:
            context.diagnostic(
                DiagnosticCode.METADATA_MALFORMED, "npm package name is missing or invalid", source=metadata_path
            )
            continue
        canonical_name = split_npm_package_spec(name)
        assert canonical_name is not None
        package_name, declared_suffix = canonical_name
        if declared_suffix is not None:
            context.diagnostic(
                DiagnosticCode.METADATA_MALFORMED, "installed npm package name contains a version", source=metadata_path
            )
            continue
        package_version = safe_version(version)
        if version is not None and package_version is None:
            context.diagnostic(
                DiagnosticCode.METADATA_MALFORMED, "npm package version is invalid", source=metadata_path
            )
        for binary in _binaries(package_name, data.get("bin"), context, metadata_path, package_dir):
            launch = SanitizedLaunch(
                kind=LaunchKind.NPM,
                package=package_name,
                binary=binary,
                version=package_version,
            )
            if not context.add(
                DiscoveryEvidence(
                    component=None,
                    provider=ProviderKind.NPM,
                    scope=DiscoveryScope.GLOBAL,
                    source_path=metadata_path,
                    display_path=context.display_path(metadata_path),
                    package_ecosystem=PackageEcosystem.NPM,
                    package_name=package_name,
                    package_version=package_version,
                    launch=launch,
                )
            ):
                break

    context.result.evidence.sort(
        key=lambda item: (item.package_name or "", item.launch.binary if item.launch and item.launch.binary else "")
    )
    context.result.diagnostics.sort(key=lambda item: (item.source or "", item.code.value, item.message))
    return context.result
