# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from observal_cli.discovery.models import DiagnosticCode
from observal_cli.discovery.providers._utils import CommandOutput
from observal_cli.discovery.providers.pipx import discover_pipx


def _distribution(environment, name: str, version: str, apps: tuple[str, ...] = ()):
    site = environment / "lib" / "python3.12" / "site-packages"
    dist = site / f"{name.replace('-', '_')}-{version}.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text(f"Name: {name}\nVersion: {version}\nSummary: tool\n")
    if apps:
        lines = "\n".join(f"{app} = {name}:main" for app in apps)
        (dist / "entry_points.txt").write_text(f"[console_scripts]\n{lines}\n")
    (dist / "direct_url.json").write_text(json.dumps({"url": "https://example.test/repository"}))
    return dist


def test_pipx_parses_json_and_enriches_from_distribution_metadata(tmp_path) -> None:
    root = tmp_path / "pipx"
    environment = root / "venvs" / "Demo_Tool"
    _distribution(environment, "demo-tool", "2.0", ("demo", "demo-admin"))
    listing = {
        "venvs": {
            "Demo_Tool": {
                "metadata": {
                    "main_package": {
                        "package": "Demo.Tool",
                        "package_version": "1.0",
                        "apps": ["demo"],
                    }
                }
            }
        }
    }

    def runner(command, timeout):
        assert tuple(command) == ("pipx", "list", "--json")
        assert timeout == 5.0
        return CommandOutput(json.dumps(listing).encode())

    result = discover_pipx(runner=runner, environment={"PIPX_HOME": str(root)}, home=tmp_path)

    assert [(item.package_name, item.package_version, item.launch.binary) for item in result.evidence] == [
        ("demo-tool", "2.0", "demo"),
        ("demo-tool", "2.0", "demo-admin"),
    ]
    assert result.diagnostics == []


def test_pipx_falls_back_to_filesystem_when_json_is_unavailable(tmp_path) -> None:
    root = tmp_path / "pipx"
    _distribution(root / "venvs" / "fallback-tool", "fallback-tool", "3.1", ("fallback",))

    def missing(command, timeout):
        raise FileNotFoundError

    result = discover_pipx(runner=missing, environment={"PIPX_HOME": str(root)}, home=tmp_path)

    assert [(item.package_name, item.launch.binary) for item in result.evidence] == [("fallback-tool", "fallback")]
    assert [item.code for item in result.diagnostics] == [DiagnosticCode.EXECUTABLE_MISSING]


def test_pipx_malformed_json_falls_back_and_reports_diagnostic(tmp_path) -> None:
    root = tmp_path / "pipx"
    _distribution(root / "venvs" / "local-tool", "local-tool", "1", ("local",))

    result = discover_pipx(
        runner=lambda command, timeout: CommandOutput(b"{not-json"),
        environment={"PIPX_HOME": str(root)},
    )

    assert [item.package_name for item in result.evidence] == ["local-tool"]
    assert [item.code for item in result.diagnostics] == [DiagnosticCode.METADATA_MALFORMED]


def test_pipx_keeps_partial_results_for_malformed_optional_metadata(tmp_path) -> None:
    root = tmp_path / "pipx"
    dist = _distribution(root / "venvs" / "partial-tool", "partial-tool", "1", ("partial",))
    (dist / "direct_url.json").write_text("{malformed")

    result = discover_pipx(
        runner=lambda command, timeout: CommandOutput(b"malformed"),
        environment={"PIPX_HOME": str(root)},
    )

    assert [item.package_name for item in result.evidence] == ["partial-tool"]
    assert [item.code for item in result.diagnostics].count(DiagnosticCode.METADATA_MALFORMED) == 2


def test_pipx_reports_only_main_packages_not_dependencies(tmp_path) -> None:
    root = tmp_path / "pipx"
    environment = root / "venvs" / "main-tool"
    _distribution(environment, "main-tool", "1", ("main",))
    _distribution(environment, "dependency", "9", ("dependency",))

    result = discover_pipx(
        runner=lambda command, timeout: CommandOutput(b"not json"),
        environment={"PIPX_HOME": str(root)},
    )

    assert [item.package_name for item in result.evidence] == ["main-tool"]


def test_pipx_does_not_return_secret_like_json_metadata(tmp_path) -> None:
    root = tmp_path / "pipx"
    root.mkdir()
    secret = "super-secret-token-value"
    listing = {
        "venvs": {
            "unsafe": {
                "metadata": {
                    "main_package": {
                        "package": f"token={secret}",
                        "package_version": secret,
                        "apps": [f"token={secret}"],
                    }
                }
            }
        }
    }

    result = discover_pipx(
        runner=lambda command, timeout: CommandOutput(json.dumps(listing).encode()),
        environment={"PIPX_HOME": str(root)},
    )

    assert secret not in repr(result)
    assert result.evidence == []
    assert [item.code for item in result.diagnostics] == [DiagnosticCode.METADATA_MALFORMED]


def test_pipx_item_limit_is_stable(tmp_path) -> None:
    root = tmp_path / "pipx"
    _distribution(root / "venvs" / "alpha", "alpha", "1")
    _distribution(root / "venvs" / "zeta", "zeta", "1")

    result = discover_pipx(
        runner=lambda command, timeout: CommandOutput(b"invalid"),
        environment={"PIPX_HOME": str(root)},
        max_records=1,
    )

    assert [item.package_name for item in result.evidence] == ["alpha"]
    assert [item.code for item in result.diagnostics].count(DiagnosticCode.ITEM_LIMIT_REACHED) == 1
