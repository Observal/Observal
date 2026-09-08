# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Helpers for inspecting top-level Python tool distribution metadata."""

from __future__ import annotations

import configparser
import json
from dataclasses import dataclass
from email.parser import Parser
from typing import TYPE_CHECKING

from observal_cli.discovery.models import DiagnosticCode
from observal_cli.discovery.providers._utils import (
    ProviderContext,
    contained_directory,
    safe_executable_name,
    safe_python_package_name,
    safe_version,
    sorted_children,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class PythonDistribution:
    name: str
    version: str | None
    apps: tuple[str, ...]
    metadata_path: Path


def site_package_roots(environment: Path, context: ProviderContext) -> list[Path]:
    candidates = [environment / "Lib" / "site-packages"]
    lib = environment / "lib"
    if contained_directory(environment, lib, context) is not None:
        for child in sorted_children(lib, context):
            if child.name.startswith("python"):
                candidates.append(child / "site-packages")
    roots: list[Path] = []
    for candidate in candidates:
        contained = contained_directory(environment, candidate, context)
        if contained is not None:
            roots.append(contained)
    return roots


def inspect_distribution(
    environment: Path,
    expected_name: str,
    context: ProviderContext,
) -> PythonDistribution | None:
    expected = safe_python_package_name(expected_name)
    if expected is None:
        return None
    for site_root in site_package_roots(environment, context):
        for dist_info in sorted_children(site_root, context):
            if not dist_info.name.endswith(".dist-info"):
                continue
            contained = contained_directory(site_root, dist_info, context)
            if contained is None:
                continue
            metadata_path = contained / "METADATA"
            raw = context.read_metadata(site_root, metadata_path)
            if raw is None:
                continue
            try:
                metadata = Parser().parsestr(raw)
            except (TypeError, ValueError):
                context.diagnostic(
                    DiagnosticCode.METADATA_MALFORMED,
                    "Python distribution metadata is malformed",
                    source=metadata_path,
                )
                continue
            name = safe_python_package_name(metadata.get("Name"))
            if name != expected:
                continue
            raw_version = metadata.get("Version")
            version = safe_version(raw_version)
            if raw_version is not None and version is None:
                context.diagnostic(
                    DiagnosticCode.METADATA_MALFORMED,
                    "Python distribution version is invalid",
                    source=metadata_path,
                )
            apps: list[str] = []
            entry_points_path = contained / "entry_points.txt"
            entry_points = context.read_metadata(site_root, entry_points_path)
            if entry_points is not None:
                parser = configparser.ConfigParser(interpolation=None)
                try:
                    parser.read_string(entry_points)
                    if parser.has_section("console_scripts"):
                        raw_apps = [name for name, _ in parser.items("console_scripts")]
                        apps = sorted(
                            (app for value in raw_apps if (app := safe_executable_name(value)) is not None),
                            key=str.casefold,
                        )
                        if len(apps) != len(raw_apps):
                            context.diagnostic(
                                DiagnosticCode.METADATA_MALFORMED,
                                "Python console entry-point name is invalid",
                                source=entry_points_path,
                            )
                except configparser.Error:
                    context.diagnostic(
                        DiagnosticCode.METADATA_MALFORMED,
                        "Python console entry-point metadata is malformed",
                        source=entry_points_path,
                    )
            direct_url_path = contained / "direct_url.json"
            direct_url = context.read_metadata(site_root, direct_url_path)
            if direct_url is not None:
                try:
                    if not isinstance(json.loads(direct_url), dict):
                        raise ValueError
                except (json.JSONDecodeError, ValueError):
                    context.diagnostic(
                        DiagnosticCode.METADATA_MALFORMED,
                        "Python direct URL metadata is malformed",
                        source=direct_url_path,
                    )
            return PythonDistribution(
                name=name,
                version=version,
                apps=tuple(apps),
                metadata_path=metadata_path,
            )
    return None
