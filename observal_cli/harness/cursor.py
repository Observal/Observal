# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Cursor harness adapter."""

from __future__ import annotations

import time
from pathlib import Path

from observal_cli.discovery.adapter_support import RichAdapterScanner, project_legacy
from observal_cli.discovery.models import AdapterDiscoveryResult, DiscoveryScope
from observal_cli.harness import (
    HookSpec,
    ScanResult,
    SessionSource,
    register_adapter,
)
from observal_cli.harness.base import BaseAdapter


class CursorAdapter(BaseAdapter):
    """Adapter for Cursor."""

    home_markers = (".cursor",)
    managed_agent_profiles = (
        "user:agents/{name}.md",
        "project:.cursor/agents/{name}.md",
    )
    managed_skills = ("user:rules/{name}.mdc", "user:skills/{name}/SKILL.md")

    @property
    def harness_name(self) -> str:
        return "cursor"

    def resolve_session_source(self, event: dict, home: Path | None = None) -> SessionSource | None:
        from observal_cli.sessions.cursor import find_cursor_jsonl, get_parent_session_id, project_key_from_cwd

        session_id = str(event.get("conversationId") or event.get("conversation_id") or event.get("session_id") or "")
        if not session_id:
            return None
        transcript = str(event.get("transcriptPath") or event.get("transcript_path") or "")
        path = Path(transcript) if transcript else None
        if path is None or not path.is_file():
            workspace = str(event.get("workspacePath") or event.get("cwd") or "")
            roots = event.get("workspace_roots") or []
            cwd = workspace or (str(roots[0]) if roots else "")
            path = find_cursor_jsonl(session_id, project_key_from_cwd(cwd), home=home)
        else:
            cwd = str(event.get("workspacePath") or event.get("cwd") or "")
        if path is None:
            return None
        parent_session_id = get_parent_session_id(path)
        subagent_id = path.stem.removeprefix("agent-")
        return SessionSource(
            self.harness_name,
            subagent_id if parent_session_id else session_id,
            path,
            cwd=cwd,
            cursor_key=f"{parent_session_id}__sub__{subagent_id}" if parent_session_id else None,
            parent_session_id=parent_session_id,
        )

    def discover_session_sources(
        self,
        home: Path | None = None,
        since_hours: int = 168,
    ) -> list[SessionSource]:
        from observal_cli.sessions.cursor import get_parent_session_id

        home = home or Path.home()
        root = home / ".cursor" / "projects"
        if not root.is_dir():
            return []
        cutoff = time.time() - since_hours * 3600
        sources: dict[str, SessionSource] = {}
        for path in root.glob("**/*.jsonl"):
            try:
                if path.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            parent_session_id = get_parent_session_id(path)
            session_id = path.stem.removeprefix("agent-")
            cursor_key = f"{parent_session_id}__sub__{session_id}" if parent_session_id else None
            key = cursor_key or session_id
            sources[key] = SessionSource(
                self.harness_name,
                session_id,
                path,
                cursor_key=cursor_key,
                parent_session_id=parent_session_id,
            )
        return sorted(sources.values(), key=lambda source: source.path.stat().st_mtime, reverse=True)

    def related_session_sources(self, source: SessionSource, home: Path | None = None) -> list[SessionSource]:
        if source.path is None or source.parent_session_id is not None:
            return []
        directories = (source.path.parent / "subagents", source.path.parent / source.session_id / "subagents")
        paths = {path for directory in directories if directory.is_dir() for path in directory.glob("agent-*.jsonl")}
        related: list[SessionSource] = []
        for path in sorted(paths):
            subagent_id = path.stem.removeprefix("agent-")
            related.append(
                SessionSource(
                    self.harness_name,
                    subagent_id,
                    path,
                    cwd=source.cwd,
                    cursor_key=f"{source.session_id}__sub__{subagent_id}",
                    parent_session_id=source.session_id,
                )
            )
        return related

    def session_extra_records(
        self,
        source: SessionSource,
        event: dict,
        final: bool,
        home: Path | None = None,
    ) -> tuple[str, ...]:
        if not final or source.parent_session_id is not None:
            return ()
        from observal_cli.sessions.cursor import build_usage_line

        usage = build_usage_line(event)
        return (usage,) if usage else ()

    def defer_session_delivery(self) -> bool:
        return True

    def scan_home(self, home: Path | None = None) -> ScanResult:
        return project_legacy(self.discover_home(home))

    def scan_project(self, project_dir: Path) -> ScanResult:
        return project_legacy(self.discover_project(project_dir))

    def discover_home(self, home: Path | None = None) -> AdapterDiscoveryResult:
        home = home or Path.home()
        return self._discover_cursor_root(home / ".cursor", DiscoveryScope.USER, home=home)

    def discover_project(self, project_dir: Path) -> AdapterDiscoveryResult:
        return self._discover_cursor_root(
            project_dir / ".cursor",
            DiscoveryScope.PROJECT,
            project_dir=project_dir,
        )

    def _discover_cursor_root(
        self,
        root: Path,
        scope: DiscoveryScope,
        *,
        home: Path | None = None,
        project_dir: Path | None = None,
    ) -> AdapterDiscoveryResult:
        scanner = RichAdapterScanner(
            harness=self.harness_name,
            scope=scope,
            root=root,
            home=home,
            project_dir=project_dir,
        )
        source = "cursor:global" if scope is DiscoveryScope.USER else "cursor:project"
        scanner.add_mcp_config(root / "mcp.json", source=source, description_prefix="Cursor MCP")
        scanner.add_markdown_agents(root / "agents", source_prefix="Cursor agent")
        scanner.add_skills(root / "skills", source="cursor:skills", prefix="Cursor skill")
        hooks_file = root / "hooks.json"
        hooks_data = scanner.read_json(hooks_file)
        if hooks_data is not None:
            scanner.add_hooks_mapping(
                hooks_file, hooks_data.get("hooks", hooks_data), name_prefix="cursor", source=source
            )
        return scanner.finish()

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=["tool_call", "tool_result"],
            format="http",
            markers=["observal", "OBSERVAL"],
        )

    def detect_hooks(self, config_dir: Path) -> str:
        return "none"

    def allow_home_agent_profile(self, is_user_scope: bool) -> bool:
        return False

    def patch_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _patch_cursor

        return _patch_cursor(dry_run)

    def cleanup_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _cleanup_cursor

        return _cleanup_cursor(dry_run)


register_adapter(CursorAdapter())
