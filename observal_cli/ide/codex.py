# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Codex CLI IDE adapter."""

from __future__ import annotations

from pathlib import Path

from observal_cli.ide import (
    DiscoveredMcp,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.ide.base import BaseAdapter


class CodexAdapter(BaseAdapter):
    """Adapter for Codex CLI (OpenAI)."""

    @property
    def ide_name(self) -> str:
        return "codex"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        from observal_cli.cmd_scan import _scan_codex_home

        home = home or Path.home()
        codex_dir = home / ".codex"
        if not codex_dir.exists():
            return ScanResult()
        mcps, skills, hooks, agents = _scan_codex_home(codex_dir)
        return ScanResult(mcps=mcps, skills=skills, hooks=hooks, agents=agents)

    def scan_project(self, project_dir: Path) -> ScanResult:
        return ScanResult()

    def get_hook_spec(self) -> HookSpec:
        return HookSpec()  # Codex uses OTel, not hooks

    def detect_hooks(self, config_dir: Path) -> str:
        return "none"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)


register_adapter(CodexAdapter())
