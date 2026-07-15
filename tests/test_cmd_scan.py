# SPDX-FileCopyrightText: 2026 Anupam Kumar <anupam9594.kumar@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import typer
from typer.testing import CliRunner

from observal_cli.cmd_scan import register_scan

runner = CliRunner()


def _make_app() -> typer.Typer:
    app = typer.Typer()
    register_scan(app)
    return app


def _mcp(
    name: str,
    command: str = "npx",
    args: list | None = None,
    url: str | None = None,
    source: str = "cursor:global",
):
    m = MagicMock()
    m.name = name
    m.command = command
    m.args = args or []
    m.url = url
    m.source = source
    m.display_cmd.return_value = f"{command} {' '.join(args or [])}"
    return m


def _scan_result(mcps=None, skills=None, hooks=None, agents=None):
    return SimpleNamespace(
        mcps=mcps or [],
        skills=skills or [],
        hooks=hooks or [],
        agents=agents or [],
    )


def _make_adapter(home_result=None, project_result=None, hook_status="missing"):
    adapter = MagicMock()
    adapter.scan_home.return_value = home_result or _scan_result()
    adapter.scan_project.return_value = project_result or _scan_result()
    adapter.detect_hooks.return_value = hook_status
    return adapter


@contextmanager
def _noop_spinner(_msg=""):
    yield


_PATCH_ENSURE = "observal_cli.cmd_scan.ensure_loaded"
_PATCH_GET_ALL = "observal_cli.cmd_scan.get_all_adapters"
_PATCH_GET_ONE = "observal_cli.cmd_scan.get_adapter"
_PATCH_HOME = "observal_cli.cmd_scan.Path.home"
_PATCH_SHIMMED = "observal_cli.cmd_scan._is_already_shimmed"
_PATCH_SPINNER = "observal_cli.cmd_scan.spinner"
_PATCH_ISDIR = "pathlib.Path.is_dir"


class TestScanNoIdes:
    def test_no_ides_found_prints_message_and_exits_1(self, tmp_path):
        adapter = _make_adapter()
        app = _make_app()

        with (
            patch(_PATCH_ENSURE),
            patch(_PATCH_GET_ALL, return_value={"cursor": adapter}),
            patch(_PATCH_HOME, return_value=tmp_path),
            patch(_PATCH_SHIMMED, return_value=False),
            patch(_PATCH_SPINNER, side_effect=_noop_spinner),
            patch(_PATCH_ISDIR, return_value=False),
        ):
            result = runner.invoke(app, [])

        assert result.exit_code == 1
        assert "No IDE configurations found" in result.output


class TestScanOneMcp:
    def test_single_ide_single_mcp_appears_in_output(self, tmp_path):
        mcp = _mcp("my-server")
        adapter = _make_adapter(home_result=_scan_result(mcps=[mcp]))
        app = _make_app()

        with (
            patch(_PATCH_ENSURE),
            patch(_PATCH_GET_ALL, return_value={"cursor": adapter}),
            patch(_PATCH_GET_ONE, return_value=adapter),
            patch(_PATCH_HOME, return_value=tmp_path),
            patch(_PATCH_SHIMMED, return_value=False),
            patch(_PATCH_SPINNER, side_effect=_noop_spinner),
            patch(_PATCH_ISDIR, return_value=True),
        ):
            result = runner.invoke(app, [])

        assert result.exit_code == 0
        assert "my-server" in result.output

    def test_single_ide_shows_component_count(self, tmp_path):
        mcp = _mcp("server-a")
        adapter = _make_adapter(home_result=_scan_result(mcps=[mcp]))
        app = _make_app()

        with (
            patch(_PATCH_ENSURE),
            patch(_PATCH_GET_ALL, return_value={"cursor": adapter}),
            patch(_PATCH_GET_ONE, return_value=adapter),
            patch(_PATCH_HOME, return_value=tmp_path),
            patch(_PATCH_SHIMMED, return_value=False),
            patch(_PATCH_SPINNER, side_effect=_noop_spinner),
            patch(_PATCH_ISDIR, return_value=True),
        ):
            result = runner.invoke(app, [])

        assert result.exit_code == 0
        assert "1 components discovered" in result.output


class TestScanIdeFilter:
    def test_unknown_ide_exits_1_with_error(self, tmp_path):
        app = _make_app()

        with (
            patch(_PATCH_ENSURE),
            patch(
                _PATCH_GET_ALL,
                return_value={"cursor": _make_adapter(), "kiro": _make_adapter()},
            ),
            patch(_PATCH_GET_ONE, side_effect=KeyError("no such ide")),
            patch(_PATCH_HOME, return_value=tmp_path),
            patch(_PATCH_SPINNER, side_effect=_noop_spinner),
            patch(_PATCH_ISDIR, return_value=False),
        ):
            result = runner.invoke(app, ["--ide", "totally-unknown-ide"])

        assert result.exit_code == 1
        assert "Unknown IDE" in result.output

    def test_known_ide_filter_only_calls_that_adapter(self, tmp_path):
        cursor_adapter = _make_adapter(
            home_result=_scan_result(mcps=[_mcp("cursor-mcp")])
        )
        kiro_adapter = _make_adapter()
        app = _make_app()

        with (
            patch(_PATCH_ENSURE),
            patch(
                _PATCH_GET_ALL,
                return_value={"cursor": cursor_adapter, "kiro": kiro_adapter},
            ),
            patch(_PATCH_GET_ONE, return_value=cursor_adapter),
            patch(_PATCH_HOME, return_value=tmp_path),
            patch(_PATCH_SHIMMED, return_value=False),
            patch(_PATCH_SPINNER, side_effect=_noop_spinner),
            patch(_PATCH_ISDIR, return_value=True),
        ):
            result = runner.invoke(app, ["--ide", "cursor"])

        kiro_adapter.scan_home.assert_not_called()
        assert result.exit_code == 0


class TestScanDeduplication:
    def test_same_mcp_name_from_home_and_project_counted_once(self, tmp_path):
        shared_name = "shared-mcp"
        adapter = _make_adapter(
            home_result=_scan_result(mcps=[_mcp(shared_name, source="cursor:global")]),
            project_result=_scan_result(
                mcps=[_mcp(shared_name, source="cursor:project")]
            ),
        )
        app = _make_app()

        with (
            patch(_PATCH_ENSURE),
            patch(_PATCH_GET_ALL, return_value={"cursor": adapter}),
            patch(_PATCH_GET_ONE, return_value=adapter),
            patch(_PATCH_HOME, return_value=tmp_path),
            patch(_PATCH_SHIMMED, return_value=False),
            patch(_PATCH_SPINNER, side_effect=_noop_spinner),
            patch(_PATCH_ISDIR, return_value=True),
        ):
            result = runner.invoke(app, [])

        assert result.exit_code == 0
        assert "1 components discovered" in result.output
