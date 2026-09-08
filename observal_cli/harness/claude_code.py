# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Claude Code harness adapter."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from observal_cli.discovery.adapter_support import RichAdapterScanner, project_legacy
from observal_cli.discovery.models import AdapterDiscoveryResult, DiagnosticCode, DiscoveryScope
from observal_cli.discovery.redact import redact_text
from observal_cli.harness import (
    DiscoveredSkill,
    HookSpec,
    ScanResult,
    SessionSource,
    register_adapter,
)
from observal_cli.harness.base import BaseAdapter
from observal_cli.shared.utils import (
    _OBSERVAL_HOOK_MARKERS,
    first_content_line,
    parse_frontmatter_field,
)

if TYPE_CHECKING:
    from observal_cli.discovery.bounded_walk import AggregateDiscoveryBudget


class ClaudeCodeAdapter(BaseAdapter):
    """Adapter for Claude Code (Anthropic)."""

    home_markers = (".claude",)
    managed_agent_profiles = ("user:agents/{name}.md", "project:.claude/agents/{name}.md")
    managed_skills = ("user:skills/{name}/SKILL.md",)

    @property
    def harness_name(self) -> str:
        return "claude-code"

    def resolve_session_source(self, event: dict[str, Any], home: Path | None = None) -> SessionSource | None:
        from observal_cli.sessions.claude_code import (
            find_jsonl_file,
            get_parent_session_id,
            project_key_from_cwd,
        )

        session_id = str(event.get("session_id") or "")
        cwd = str(event.get("cwd") or "")
        if not session_id:
            return None
        path = find_jsonl_file(session_id, project_key_from_cwd(cwd), home=home)
        if path is None:
            return None
        parent_session_id = get_parent_session_id(path)
        cursor_key = None
        if parent_session_id:
            cursor_key = f"{parent_session_id}__sub__{path.stem.removeprefix('agent-')}"
        return SessionSource(
            harness=self.harness_name,
            session_id=path.stem.removeprefix("agent-") if parent_session_id else session_id,
            path=path,
            cwd=cwd,
            cursor_key=cursor_key,
            parent_session_id=parent_session_id,
        )

    def discover_session_sources(
        self,
        home: Path | None = None,
        since_hours: int = 168,
    ) -> list[SessionSource]:
        from observal_cli.sessions.claude_code import find_sessions_dir

        cutoff = time.time() - since_hours * 3600
        root = find_sessions_dir(home)
        if not root.is_dir():
            return []
        sources: list[SessionSource] = []
        for path in root.glob("*/*.jsonl"):
            if self._recent(path, cutoff):
                sources.append(SessionSource(self.harness_name, path.stem, path))
        for path in root.glob("*/*/subagents/*.jsonl"):
            if not self._recent(path, cutoff):
                continue
            parent_session_id = path.parts[-3]
            subagent_id = path.stem.removeprefix("agent-")
            sources.append(
                SessionSource(
                    self.harness_name,
                    subagent_id,
                    path,
                    cursor_key=f"{parent_session_id}__sub__{subagent_id}",
                    parent_session_id=parent_session_id,
                )
            )
        return sorted(sources, key=lambda source: str(source.path))

    def related_session_sources(self, source: SessionSource, home: Path | None = None) -> list[SessionSource]:
        if source.path is None or source.parent_session_id is not None:
            return []
        subagents_dir = source.path.parent / source.session_id / "subagents"
        if not subagents_dir.is_dir():
            return []
        related: list[SessionSource] = []
        for path in sorted(subagents_dir.glob("agent-*.jsonl")):
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

    @staticmethod
    def _recent(path: Path, cutoff: float) -> bool:
        try:
            return path.stat().st_mtime >= cutoff
        except OSError:
            return False

    def scan_home(self, home: Path | None = None) -> ScanResult:
        return project_legacy(self.discover_home(home))

    def scan_project(self, project_dir: Path) -> ScanResult:
        return project_legacy(self.discover_project(project_dir))

    def discover_home(self, home: Path | None = None) -> AdapterDiscoveryResult:
        home = home or Path.home()
        return self._discover_claude_home(home / ".claude", home)

    def discover_project(self, project_dir: Path) -> AdapterDiscoveryResult:
        scanner = RichAdapterScanner(
            harness=self.harness_name,
            scope=DiscoveryScope.PROJECT,
            root=project_dir,
            project_dir=project_dir,
        )
        scanner.add_mcp_config(
            project_dir / ".mcp.json",
            source="claude-code:project",
            description_prefix="Claude Code project MCP",
        )
        settings_path = project_dir / ".claude" / "settings.json"
        settings = scanner.read_json(settings_path)
        if settings is not None:
            scanner.add_hooks_mapping(
                settings_path,
                settings.get("hooks", {}),
                name_prefix="claude-code:project",
                source="claude-code:project",
            )
        scanner.add_skills(project_dir / ".claude" / "skills", source="claude:skills", prefix="Skill")
        scanner.add_markdown_agents(project_dir / ".claude" / "agents", source_prefix="Agent")
        return scanner.finish()

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=[
                "PreToolUse",
                "PostToolUse",
                "Notification",
                "Stop",
                "SubagentStop",
            ],
            format="command",
            markers=["observal", "OBSERVAL"],
        )

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        from observal_cli.harness_specs.claude_code_hooks_spec import get_desired_hooks

        return get_desired_hooks()

    def detect_hooks(self, config_dir: Path) -> str:
        settings = config_dir / "settings.json"
        if not settings.exists():
            return "missing"
        try:
            data = json.loads(settings.read_text())
        except (json.JSONDecodeError, OSError):
            return "missing"
        hooks = data.get("hooks", {})
        if not hooks:
            return "missing"
        found = 0
        for _evt, groups in hooks.items():
            if not isinstance(groups, list):
                continue
            for g in groups:
                for h in g.get("hooks", []):
                    cmd = h.get("command", "")
                    url = h.get("url", "")
                    if any(m in cmd or m in url for m in _OBSERVAL_HOOK_MARKERS):
                        found += 1
                        break
        return "installed" if found >= 3 else ("partial" if found > 0 else "missing")

    # ── Private scanning helpers ──────────────────────────────────

    def _scan_claude_dir(self, claude_dir: Path) -> ScanResult:
        """Compatibility projection for callers that already resolved ``.claude``."""
        return project_legacy(self._discover_claude_home(claude_dir, claude_dir.parent))

    def _discover_claude_home(self, claude_dir: Path, home: Path) -> AdapterDiscoveryResult:
        scanner = RichAdapterScanner(
            harness=self.harness_name,
            scope=DiscoveryScope.USER,
            root=claude_dir,
            home=home,
        )
        budget = scanner.walker.budget
        deadline = scanner.walker.deadline
        settings_path = claude_dir / "settings.json"
        settings = scanner.read_json(settings_path)
        active_plugins: set[str] = set()
        if settings is not None:
            scanner.add_mcps(
                settings.get("mcpServers", {}),
                settings_path,
                source="claude-code:global",
                description_prefix="Claude Code global MCP",
            )
            scanner.add_hooks_mapping(
                settings_path,
                settings.get("hooks", {}),
                name_prefix="claude-code",
                source="claude-code:global",
            )
            enabled = settings.get("enabledPlugins", {})
            if isinstance(enabled, Mapping):
                active_plugins = {str(name) for name, value in enabled.items() if value is True}
            else:
                scanner.diagnostic(
                    DiagnosticCode.METADATA_MALFORMED,
                    settings_path,
                    "Claude enabledPlugins must be an object",
                )

        # User skills and agents are independent of settings.json.
        scanner.add_skills(claude_dir / "skills", source="claude:skills", prefix="Skill")
        scanner.add_markdown_agents(claude_dir / "agents", source_prefix="Agent")

        plugin_paths: dict[str, Path] = {}
        installed_path = claude_dir / "plugins" / "installed_plugins.json"
        installed = scanner.read_json(installed_path) if active_plugins else None
        if installed is not None:
            plugins = installed.get("plugins", {})
            if not isinstance(plugins, Mapping):
                scanner.diagnostic(
                    DiagnosticCode.METADATA_MALFORMED,
                    installed_path,
                    "Claude installed plugin registry must contain an object",
                )
            else:
                for plugin_key in sorted(active_plugins, key=str.casefold):
                    entries = plugins.get(plugin_key)
                    if entries is None:
                        continue
                    if not isinstance(entries, list) or not entries or not isinstance(entries[0], Mapping):
                        scanner.diagnostic(
                            DiagnosticCode.METADATA_MALFORMED,
                            installed_path,
                            "Claude installed plugin entry must be a non-empty array of objects",
                        )
                        continue
                    install_path = entries[0].get("installPath")
                    if not isinstance(install_path, str) or not install_path.strip():
                        scanner.diagnostic(
                            DiagnosticCode.METADATA_MALFORMED,
                            installed_path,
                            "Claude installed plugin entry is missing installPath",
                        )
                        continue
                    candidate = Path(install_path).expanduser()
                    try:
                        resolved = candidate.resolve(strict=True)
                    except (OSError, RuntimeError):
                        scanner.diagnostic(
                            DiagnosticCode.PERMISSION_DENIED,
                            installed_path,
                            "Claude plugin install root is missing or unreadable",
                        )
                        continue
                    if not resolved.is_dir():
                        scanner.diagnostic(
                            DiagnosticCode.METADATA_MALFORMED,
                            installed_path,
                            "Claude plugin install root is not a directory",
                        )
                        continue
                    plugin_paths[plugin_key] = resolved

        for plugin_key in sorted(active_plugins, key=str.casefold):
            if plugin_key not in plugin_paths:
                cached = self._cached_plugin_root(claude_dir, plugin_key, scanner)
                if cached is not None:
                    plugin_paths[plugin_key] = cached

        result = scanner.finish()
        aggregate_limit_codes = {
            DiagnosticCode.APPROVED_ROOT_LIMIT_REACHED,
            DiagnosticCode.COLLECTION_FILE_LIMIT_REACHED,
            DiagnosticCode.EVIDENCE_LIMIT_REACHED,
        }
        for plugin_key in sorted(plugin_paths, key=str.casefold):
            plugin_result = self._discover_claude_plugin(
                plugin_key,
                plugin_paths[plugin_key],
                home=home,
                budget=budget,
                deadline=deadline,
            )
            result.evidence.extend(plugin_result.evidence)
            result.diagnostics.extend(plugin_result.diagnostics)
            if budget.emitted_limits.intersection(aggregate_limit_codes):
                break
        result.evidence.sort(
            key=lambda item: (
                item.display_path or "",
                str(getattr(item.component, "name", "")).casefold(),
                type(item.component).__name__,
            )
        )
        result.diagnostics.sort(key=lambda item: (item.source or "", item.code.value, item.message))
        return result

    def _cached_plugin_root(
        self,
        claude_dir: Path,
        plugin_key: str,
        scanner: RichAdapterScanner,
    ) -> Path | None:
        name, separator, marketplace = plugin_key.partition("@")
        market_dir = (
            claude_dir / "plugins" / "cache" / marketplace / name
            if separator
            else claude_dir / "plugins" / "cache" / name / name
        )
        if not market_dir.is_dir():
            return None
        try:
            versions = [path for path in market_dir.iterdir() if path.is_dir() and not path.is_symlink()]
            versions.sort(key=lambda path: (-path.stat().st_mtime, path.name.casefold()))
        except OSError as exc:
            scanner.diagnostic(
                DiagnosticCode.PERMISSION_DENIED,
                market_dir,
                f"unable to inspect Claude plugin cache metadata: {exc}",
            )
            return None
        if len(versions) > scanner.walker.limits.max_files_per_root:
            scanner.diagnostic(
                DiagnosticCode.ITEM_LIMIT_REACHED,
                market_dir,
                "Claude plugin cache version limit reached",
            )
            versions = versions[: scanner.walker.limits.max_files_per_root]
        return versions[0].resolve(strict=False) if versions else None

    def _discover_claude_plugin(
        self,
        plugin_key: str,
        plugin_dir: Path,
        *,
        home: Path,
        budget: AggregateDiscoveryBudget,
        deadline: float,
    ) -> AdapterDiscoveryResult:
        scanner = RichAdapterScanner(
            harness=self.harness_name,
            scope=DiscoveryScope.USER,
            root=plugin_dir,
            home=home,
            budget=budget,
            deadline=deadline,
        )
        plugin_name = redact_text(plugin_key.split("@", 1)[0])
        description = f"Plugin: {plugin_name}"
        metadata_path = plugin_dir / ".claude-plugin" / "plugin.json"
        metadata = scanner.read_json(metadata_path)
        if metadata is not None and isinstance(metadata.get("description"), str):
            description = redact_text(metadata["description"])
        scanner.add_mcp_config(
            plugin_dir / ".mcp.json",
            source=f"plugin:{plugin_name}",
            description_prefix="Plugin MCP",
            description=description,
        )
        for skill_path in scanner.walker.files(plugin_dir, name="SKILL.md"):
            content = scanner.walker.read_text(skill_path)
            if content is None:
                continue
            skill_name = redact_text(skill_path.parent.name)
            skill_description = parse_frontmatter_field(content, "description") or first_content_line(content)
            scanner.add_component(
                DiscoveredSkill(
                    name=f"{plugin_name}/{skill_name}",
                    description=redact_text(skill_description or f"Skill from {plugin_name}"),
                    source=f"plugin:{plugin_name}",
                ),
                skill_path,
            )
        for hooks_path in scanner.walker.files(plugin_dir, name="hooks.json"):
            hooks_data = scanner.read_json(hooks_path)
            if hooks_data is not None:
                scanner.add_hooks_mapping(
                    hooks_path,
                    hooks_data.get("hooks", {}),
                    name_prefix=plugin_name,
                    source=f"plugin:{plugin_name}",
                )
        return scanner.finish()

    def saved_model(self, agent_detail: dict | None) -> str | None:
        saved = super().saved_model(agent_detail)
        if saved or not agent_detail:
            return saved
        legacy = agent_detail.get("model_name")
        return legacy.strip() if isinstance(legacy, str) and legacy.strip() else None

    def apply_install_options(self, options: dict, tools: str | None) -> None:
        if tools:
            options["tools"] = tools

    def patch_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _patch_claude_code

        return _patch_claude_code(dry_run)

    def cleanup_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _cleanup_claude_code

        return _cleanup_claude_code(dry_run)


register_adapter(ClaudeCodeAdapter())
