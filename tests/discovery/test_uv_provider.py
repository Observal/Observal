# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from observal_cli.discovery.models import DiagnosticCode
from observal_cli.discovery.providers._utils import CommandOutput
from observal_cli.discovery.providers.uv import discover_uv


def _distribution(environment, name: str, version: str, apps: tuple[str, ...] = ()):
    dist = environment / "lib" / "python3.12" / "site-packages" / f"{name.replace('-', '_')}-{version}.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n")
    if apps:
        entries = "\n".join(f"{app} = {name}:main" for app in apps)
        (dist / "entry_points.txt").write_text(f"[console_scripts]\n{entries}\n")
    return dist


def _runner(root, listing: str):
    calls = []

    def run(command, timeout):
        calls.append(tuple(command))
        if tuple(command) == ("uv", "tool", "dir"):
            return CommandOutput(str(root).encode())
        if tuple(command) == ("uv", "tool", "list"):
            return CommandOutput(listing.encode())
        raise AssertionError(command)

    run.calls = calls
    return run


def test_uv_discovers_only_tools_listed_by_uv_and_enriches_metadata(tmp_path) -> None:
    root = tmp_path / "tools"
    _distribution(root / "demo-tool", "demo-tool", "2.0", ("demo", "demo-admin"))
    _distribution(root / "dependency", "dependency", "9", ("dependency",))
    runner = _runner(root, "demo-tool v1.0\n- demo\n")

    result = discover_uv(runner=runner, home=tmp_path)

    assert [(item.package_name, item.package_version, item.launch.binary) for item in result.evidence] == [
        ("demo-tool", "2.0", "demo"),
        ("demo-tool", "2.0", "demo-admin"),
    ]
    assert all(item.package_name != "dependency" for item in result.evidence)
    assert runner.calls == [("uv", "tool", "dir"), ("uv", "tool", "list")]


def test_uv_reports_malformed_listing_and_preserves_valid_tools(tmp_path) -> None:
    root = tmp_path / "tools"
    root.mkdir()

    result = discover_uv(runner=_runner(root, "orphan data here\nvalid-tool v1\n- valid\n"))

    assert [(item.package_name, item.launch.binary) for item in result.evidence] == [("valid-tool", "valid")]
    assert [item.code for item in result.diagnostics] == [DiagnosticCode.METADATA_MALFORMED]


def test_uv_bounds_repeated_unrecognized_record_diagnostics(tmp_path) -> None:
    root = tmp_path / "tools"
    root.mkdir()

    result = discover_uv(runner=_runner(root, "???\n!!!\n@@@\n"))

    assert [item.code for item in result.diagnostics] == [DiagnosticCode.METADATA_MALFORMED]


def test_uv_rejected_tool_block_does_not_attach_apps_to_previous_tool(tmp_path) -> None:
    root = tmp_path / "tools"
    root.mkdir()

    result = discover_uv(runner=_runner(root, "valid-tool v1\n- valid\ninvalid-tool not-a-version\n- wrong-app\n"))

    assert [(item.package_name, item.launch.binary) for item in result.evidence] == [("valid-tool", "valid")]
    assert [item.code for item in result.diagnostics] == [
        DiagnosticCode.METADATA_MALFORMED,
        DiagnosticCode.METADATA_MALFORMED,
    ]


def test_uv_redacts_untrusted_application_metadata(tmp_path) -> None:
    root = tmp_path / "tools"
    root.mkdir()
    secret = "super-secret-token-value"

    result = discover_uv(runner=_runner(root, f"safe-tool v1\n- token={secret}\n"))

    assert secret not in repr(result)
    assert [(item.package_name, item.launch.binary) for item in result.evidence] == [("safe-tool", None)]
    assert [item.code for item in result.diagnostics] == [DiagnosticCode.METADATA_MALFORMED]


def test_uv_enforces_item_limit_deterministically(tmp_path) -> None:
    root = tmp_path / "tools"
    root.mkdir()

    result = discover_uv(runner=_runner(root, "alpha v1\n- alpha\nzeta v2\n- zeta\n"), max_records=1)

    assert [item.package_name for item in result.evidence] == ["alpha"]
    assert [item.code for item in result.diagnostics] == [DiagnosticCode.ITEM_LIMIT_REACHED]
