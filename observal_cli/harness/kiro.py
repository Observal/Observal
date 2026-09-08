# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Kiro harness adapter."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from observal_cli.discovery.adapter_support import RichAdapterScanner, project_legacy
from observal_cli.discovery.models import AdapterDiscoveryResult, DiagnosticCode, DiscoveryScope
from observal_cli.discovery.redact import redact_text, redact_value
from observal_cli.harness import (
    DiscoveredAgent,
    DiscoveredHook,
    HookSpec,
    ScanResult,
    SessionSource,
    register_adapter,
)
from observal_cli.harness.base import BaseAdapter
from observal_cli.shared.utils import (
    _OBSERVAL_HOOK_MARKERS,
)


class KiroAdapter(BaseAdapter):
    """Adapter for Kiro (AWS)."""

    home_markers = (".kiro",)
    managed_agent_profiles = ("user:agents/{name}.json", "project:.kiro/agents/{name}.json")
    managed_skills = ("user:skills/{name}/SKILL.md",)

    @property
    def harness_name(self) -> str:
        return "kiro"

    def resolve_session_source(self, event: dict[str, Any], home: Path | None = None) -> SessionSource | None:
        from observal_cli.sessions.kiro import find_kiro_jsonl, read_kiro_session_cwd, resolve_session_id

        session_id = resolve_session_id(event)
        if not session_id:
            return None
        home = home or Path.home()
        path = find_kiro_jsonl(session_id, home=home)
        if path is None:
            return None
        return SessionSource(
            harness=self.harness_name,
            session_id=session_id,
            path=path,
            cwd=read_kiro_session_cwd(path),
        )

    def discover_session_sources(
        self,
        home: Path | None = None,
        since_hours: int = 168,
    ) -> list[SessionSource]:
        from observal_cli.sessions.kiro import find_sessions_dir, read_kiro_session_cwd

        cutoff = time.time() - since_hours * 3600
        root = find_sessions_dir(home)
        if not root.is_dir():
            return []
        sources: list[SessionSource] = []
        for path in sorted(root.glob("*.jsonl")):
            try:
                if path.stat().st_mtime >= cutoff:
                    sources.append(
                        SessionSource(
                            self.harness_name,
                            path.stem,
                            path,
                            cwd=read_kiro_session_cwd(path),
                        )
                    )
            except OSError:
                continue
        return sources

    def resolve_session_agent_identity(
        self,
        session_jsonl: Path | None,
        cwd: str,
    ) -> tuple[str | None, str | None] | None:
        """Resolve Kiro identity from session metadata, never the global hook environment."""
        from observal_cli.lockfile import get_agent_by_name
        from observal_cli.sessions.kiro import read_kiro_agent_name

        agent_name = read_kiro_agent_name(session_jsonl)
        if not agent_name or agent_name == "kiro_default":
            return None, None
        try:
            entry = get_agent_by_name(agent_name, harness=self.harness_name, directory=cwd or None)
        except Exception:
            return None, None
        if entry is None:
            return None, None
        return entry.get("id"), entry.get("version")

    def aged_recovery_final(self) -> bool:
        """Keep quiet Kiro sessions recoverable while they may be permission-paused."""
        return False

    def session_extra_fields(
        self,
        source: SessionSource,
        event: dict[str, Any],
        final: bool,
        home: Path | None = None,
    ) -> dict[str, Any]:
        from observal_cli.sessions.kiro import read_kiro_credits

        attempts = 5 if final else 1
        for attempt in range(attempts):
            credits = read_kiro_credits(source.session_id, home=home)
            if credits is not None:
                return {"total_credits": credits}
            if attempt < attempts - 1:
                time.sleep(0.5 * (attempt + 1))
        return {}

    def scan_home(self, home: Path | None = None) -> ScanResult:
        return project_legacy(self.discover_home(home))

    def scan_project(self, project_dir: Path) -> ScanResult:
        return project_legacy(self.discover_project(project_dir))

    def discover_home(self, home: Path | None = None) -> AdapterDiscoveryResult:
        home = home or Path.home()
        return self._discover_kiro_root(home / ".kiro", DiscoveryScope.USER, home=home)

    def discover_project(self, project_dir: Path) -> AdapterDiscoveryResult:
        return self._discover_kiro_root(
            project_dir / ".kiro",
            DiscoveryScope.PROJECT,
            project_dir=project_dir,
        )

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=[
                "on_agent_start",
                "on_agent_end",
                "on_tool_start",
                "on_tool_end",
                "on_error",
            ],
            format="http",
            markers=["observal", "OBSERVAL"],
        )

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        from observal_cli.harness_specs.kiro_hooks_spec import build_kiro_hooks

        return build_kiro_hooks(agent_id=agent_id or "")

    def detect_hooks(self, config_dir: Path) -> str:
        agents_dir = config_dir / "agents"
        if not agents_dir.is_dir():
            return "missing"
        agent_profiles = [f for f in agents_dir.glob("*.json") if f.stem != "kiro_default"]
        if not agent_profiles:
            return "missing"
        hooked = 0
        for af in agent_profiles:
            try:
                data = json.loads(af.read_text())
                hooks = data.get("hooks", {})
                for _evt, entries in hooks.items():
                    if isinstance(entries, list) and any(
                        any(m in h.get("command", "") for m in _OBSERVAL_HOOK_MARKERS)
                        for h in entries
                        if isinstance(h, dict)
                    ):
                        hooked += 1
                        break
            except (json.JSONDecodeError, OSError):
                pass
        if hooked == len(agent_profiles):
            return "installed"
        return "partial" if hooked > 0 else "missing"

    # ── Private scanning helpers ──────────────────────────────────

    def _scan_kiro_dir(self, kiro_dir: Path) -> ScanResult:
        """Compatibility projection for callers that already resolved ``.kiro``."""
        return project_legacy(self._discover_kiro_root(kiro_dir, DiscoveryScope.USER, home=kiro_dir.parent))

    def _discover_kiro_root(
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
        scope_label = "global" if scope is DiscoveryScope.USER else "project"
        base_source = f"kiro:{scope_label}"
        scanner.add_mcp_config(
            root / "settings" / "mcp.json",
            source=base_source,
            description_prefix=f"Kiro {scope_label} MCP",
        )

        for agent_path in scanner.walker.files(root / "agents", suffix=".json"):
            if agent_path.stem == "kiro_default":
                continue
            data = scanner.read_json(agent_path)
            if data is None:
                continue
            name = redact_text(str(data.get("name") or agent_path.stem))
            description = redact_text(str(data.get("description") or f"Kiro agent: {name}"))
            model = redact_text(str(data.get("model") or ""))
            prompt = redact_text(str(data.get("prompt") or ""))
            scanner.add_component(
                DiscoveredAgent(
                    name=name,
                    description=description,
                    model_name=model,
                    prompt=prompt,
                    source_file=str(agent_path),
                ),
                agent_path,
            )
            agent_source = f"kiro:agent:{name}"
            agent_mcps = data.get("mcpServers", {})
            scanner.add_mcps(
                agent_mcps,
                agent_path,
                source=agent_source,
                description_prefix=f"From Kiro agent: {name}",
            )
            scanner.add_hooks_mapping(
                agent_path,
                data.get("hooks", {}),
                name_prefix=f"kiro:{name}",
                source=agent_source,
            )

        scanner.add_skills(root / "skills", source="kiro:skills", prefix="Kiro skill")

        for hook_path in scanner.walker.files(root / "hooks", suffix=".json"):
            data = scanner.read_json(hook_path)
            if data is None:
                continue
            if "hooks" in data:
                scanner.add_hooks_mapping(
                    hook_path,
                    data["hooks"],
                    name_prefix=f"kiro:{hook_path.stem}",
                    source=base_source,
                )
                continue
            event = data.get("event") or data.get("eventName") or data.get("trigger")
            if not isinstance(event, str) or not event.strip():
                scanner.diagnostic(
                    DiagnosticCode.METADATA_MALFORMED,
                    hook_path,
                    "standalone Kiro hook is missing an event",
                )
                continue
            handler = data.get("handler", data)
            if not isinstance(handler, Mapping):
                scanner.diagnostic(
                    DiagnosticCode.METADATA_MALFORMED,
                    hook_path,
                    "standalone Kiro hook handler must be an object",
                )
                continue
            safe_handler = redact_value(handler)
            scanner.add_component(
                DiscoveredHook(
                    name=redact_text(str(data.get("name") or hook_path.stem)),
                    event=redact_text(event),
                    handler_type=redact_text(str(data.get("type") or "command")),
                    handler_config=safe_handler if isinstance(safe_handler, dict) else {},
                    description=redact_text(str(data.get("description") or f"Kiro hook: {event}")),
                    source=base_source,
                ),
                hook_path,
            )
        return scanner.finish()

    def rewrite_agent_profile(self, content: dict, agent_id: str) -> dict:
        from observal_cli.cmd_pull import _rewrite_kiro_hooks

        return _rewrite_kiro_hooks(content, agent_id=agent_id)

    def patch_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _patch_kiro

        return _patch_kiro(dry_run)

    def cleanup_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _cleanup_kiro

        return _cleanup_kiro(dry_run)

    def requires_explicit_agent_id(self) -> bool:
        return True


register_adapter(KiroAdapter())
