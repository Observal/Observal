# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Kiro harness adapter."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from observal_cli.harness import (
    DiscoveredAgent,
    DiscoveredHook,
    DiscoveredMcp,
    DiscoveredSkill,
    HookSpec,
    ScanResult,
    SessionSource,
    register_adapter,
)
from observal_cli.harness.base import BaseAdapter
from observal_cli.shared.utils import (
    _OBSERVAL_HOOK_MARKERS,
    extract_mcp_servers,
    first_content_line,
    parse_frontmatter_field,
)

_KIRO_VERSION_RE = re.compile(r"(\d+)\.(\d+)")

# Places the Kiro IDE (not the CLI) installs itself, per platform.
_KIRO_IDE_APP_PATHS = (
    "/Applications/Kiro.app",
    "~/Applications/Kiro.app",
    "~/Library/Application Support/Kiro",
    "~/.config/Kiro",
    "~/AppData/Roaming/Kiro",
    "~/AppData/Local/Programs/kiro",
)


def kiro_cli_major(home: Path | None = None) -> int | None:
    """Return the installed Kiro CLI major version, or None when undetectable."""
    override = os.environ.get("OBSERVAL_KIRO_CLI_VERSION", "").strip()
    if override:
        match = _KIRO_VERSION_RE.search(override)
        return int(match.group(1)) if match else None
    exe = shutil.which("kiro-cli") or shutil.which("kiro")
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    match = _KIRO_VERSION_RE.search(f"{proc.stdout} {proc.stderr}")
    return int(match.group(1)) if match else None


def kiro_ide_installed(home: Path | None = None) -> bool:
    """Return True when a Kiro IDE install is present on this machine.

    ``OBSERVAL_KIRO_IDE`` (``1``/``0``) overrides detection for headless setups
    and tests.
    """
    override = os.environ.get("OBSERVAL_KIRO_IDE", "").strip()
    if override:
        return override not in ("0", "false", "no")
    home = home or Path.home()
    for raw in _KIRO_IDE_APP_PATHS:
        path = Path(raw.replace("~", str(home), 1)) if raw.startswith("~") else Path(raw)
        if path.exists():
            return True
    return False


# Fields Kiro IDE 1.x treats as "CLI-only". ProfileLoader drops any JSON agent
# profile that carries one of these without also setting "permissions", logging
# reasonCode "cli_only_agent" - the agent then never appears in the IDE picker.
# Both were removed from the V3 agent schema; "permissions" replaces them.
_IDE_HOSTILE_FIELDS = ("allowedTools", "toolsSettings")


def strip_ide_hostile_fields(content: dict) -> list[str]:
    """Drop empty CLI-only tool fields so Kiro IDE will load the profile.

    Only *empty* values are removed: they are inert placeholders that Observal
    itself emitted, so dropping them cannot change behaviour on any surface. A
    non-empty value is real user configuration and is left alone (the profile
    then needs a ``permissions`` block to be IDE-visible).

    Returns the names of the fields that were removed.
    """
    if content.get("permissions") is not None:
        return []
    removed = []
    for field in _IDE_HOSTILE_FIELDS:
        if field in content and not content[field]:
            del content[field]
            removed.append(field)
    return removed


def use_inline_hooks(home: Path | None = None) -> bool:
    """Return True when this machine still needs CLI 2.x inline agent hooks.

    Inline hooks are the only format a Kiro CLI 2.x understands. The standalone
    ``.kiro/hooks/*.json`` file replaced them in IDE 1.0 and CLI 3.0, so this
    turns on the legacy format purely by CLI version.

    Having the IDE installed is deliberately *not* a reason to withhold them.
    The IDE and the CLI are separate surfaces that can coexist, and a machine
    with IDE 1.x alongside CLI 2.x needs both formats at once: the standalone
    file for the IDE, inline hooks for the CLI. Gating on the IDE meant such
    machines got neither usable format on the CLI side and silently stopped
    reporting CLI sessions. Inline hooks cost the IDE nothing - it loads an
    agent carrying them and simply never fires them.
    """
    major = kiro_cli_major(home)
    return major is not None and major < 3


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
        """Return recent transcripts from both the CLI and IDE layouts."""
        from observal_cli.sessions.kiro import (
            find_sessions_dir,
            read_kiro_session_cwd,
            sessions_root,
        )

        cutoff = time.time() - since_hours * 3600
        sources: list[SessionSource] = []

        def add(session_id: str, path: Path) -> None:
            try:
                if path.stat().st_mtime < cutoff:
                    return
            except OSError:
                return
            sources.append(
                SessionSource(
                    self.harness_name,
                    session_id,
                    path,
                    cwd=read_kiro_session_cwd(path),
                )
            )

        cli_root = find_sessions_dir(home)
        if cli_root.is_dir():
            for path in sorted(cli_root.glob("*.jsonl")):
                add(path.stem, path)

        # IDE layout: <sessions>/<workspaceHash>/<session_id>/messages.jsonl
        root = sessions_root(home)
        try:
            buckets = sorted(d for d in root.iterdir() if d.is_dir() and d.name != "cli")
        except OSError:
            buckets = []
        for bucket in buckets:
            try:
                session_dirs = sorted(d for d in bucket.iterdir() if d.is_dir())
            except OSError:
                continue
            for session_dir in session_dirs:
                transcript = session_dir / "messages.jsonl"
                if transcript.exists():
                    add(session_dir.name, transcript)

        return sources

    def resolve_session_agent_identity(
        self,
        session_jsonl: Path | None,
        cwd: str,
    ) -> tuple[str | None, str | None] | None:
        """Resolve Kiro identity from session metadata, never the global hook environment."""
        from observal_cli.lockfile import agent_entry_is_registry_backed, get_agent_by_name
        from observal_cli.sessions.kiro import read_kiro_agent_name

        agent_name = read_kiro_agent_name(session_jsonl)
        if not agent_name or agent_name == "kiro_default":
            return None, None
        try:
            entry = get_agent_by_name(agent_name, harness=self.harness_name, directory=cwd or None)
        except Exception:
            return None, None
        if not agent_entry_is_registry_backed(entry):
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
        home = home or Path.home()
        kiro_dir = home / ".kiro"
        if not kiro_dir.exists():
            return ScanResult()
        return self._scan_kiro_dir(kiro_dir)

    def scan_project(self, project_dir: Path) -> ScanResult:
        mcp_file = project_dir / ".kiro" / "settings" / "mcp.json"
        if not mcp_file.exists():
            return ScanResult()
        try:
            data = json.loads(mcp_file.read_text())
            servers = extract_mcp_servers(data)
            mcps = []
            for name, cfg in servers.items():
                mcps.append(
                    DiscoveredMcp(
                        name=name,
                        command=cfg.get("command"),
                        args=cfg.get("args", []),
                        url=cfg.get("url"),
                        description=f"Kiro project MCP: {name}",
                        source="kiro:project",
                    )
                )
            return ScanResult(mcps=mcps)
        except (json.JSONDecodeError, OSError):
            return ScanResult()

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
        """Report hook health across both the v1 hooks file and legacy inline hooks.

        The standalone ``hooks/observal.json`` file covers every agent on IDE 1.0
        and CLI 3.0, so its presence alone means hooks are installed. Only when
        it is absent do we fall back to counting legacy inline agent hooks.
        """
        if self._v1_hooks_installed(config_dir):
            return "installed"

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

    @staticmethod
    def _v1_hooks_installed(config_dir: Path) -> bool:
        from observal_cli.harness_specs.kiro_hooks_spec import (
            KIRO_V1_HOOK_FILENAME,
            is_observal_v1_hook,
        )

        hooks_file = config_dir / "hooks" / KIRO_V1_HOOK_FILENAME
        try:
            data = json.loads(hooks_file.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        if not isinstance(data, dict):
            return False
        return any(is_observal_v1_hook(h) for h in data.get("hooks") or [])

    # ── Private scanning helpers ──────────────────────────────────

    def _scan_kiro_dir(self, kiro_dir: Path) -> ScanResult:
        """Scan ~/.kiro for agents, MCP servers, and hooks."""
        mcps: list[DiscoveredMcp] = []
        skills: list[DiscoveredSkill] = []
        hooks: list[DiscoveredHook] = []
        agents: list[DiscoveredAgent] = []

        mcp_file = kiro_dir / "settings" / "mcp.json"
        if mcp_file.exists():
            try:
                mcp_data = json.loads(mcp_file.read_text())
                servers = extract_mcp_servers(mcp_data)
                for srv_name, srv_config in servers.items():
                    mcps.append(
                        DiscoveredMcp(
                            name=srv_name,
                            command=srv_config.get("command"),
                            args=srv_config.get("args", []),
                            url=srv_config.get("url"),
                            description=f"Kiro global MCP: {srv_name}",
                            source="kiro:global",
                        )
                    )
            except (json.JSONDecodeError, OSError):
                pass

        agents_dir = kiro_dir / "agents"
        if agents_dir.is_dir():
            for agent_profile in sorted(agents_dir.glob("*.json")):
                if agent_profile.stem == "kiro_default":
                    continue
                try:
                    data = json.loads(agent_profile.read_text())
                    name = data.get("name", agent_profile.stem)
                    desc = data.get("description") or ""
                    model = data.get("model") or ""
                    prompt = data.get("prompt") or ""

                    agents.append(
                        DiscoveredAgent(
                            name=name,
                            description=desc or f"Kiro agent: {name}",
                            model_name=model,
                            prompt=prompt,
                            source_file=str(agent_profile),
                        )
                    )

                    agent_mcps = data.get("mcpServers", {})
                    for srv_name, srv_config in agent_mcps.items():
                        if isinstance(srv_config, dict):
                            mcps.append(
                                DiscoveredMcp(
                                    name=srv_name,
                                    command=srv_config.get("command"),
                                    args=srv_config.get("args", []),
                                    url=srv_config.get("url"),
                                    description=f"From Kiro agent: {name}",
                                    source=f"kiro:agent:{name}",
                                )
                            )

                    agent_hooks = data.get("hooks", {})
                    for event_name, event_handlers in agent_hooks.items():
                        hook_name = f"kiro:{name}/{event_name}"
                        handler_config = {}
                        if isinstance(event_handlers, list) and event_handlers:
                            handler_config = event_handlers[0] if isinstance(event_handlers[0], dict) else {}
                        hooks.append(
                            DiscoveredHook(
                                name=hook_name,
                                event=event_name,
                                handler_type="command",
                                handler_config=handler_config,
                                description=f"Kiro hook: {event_name} on agent {name}",
                                source=f"kiro:agent:{name}",
                            )
                        )
                except (json.JSONDecodeError, OSError):
                    pass

        skills_dir = kiro_dir / "skills"
        if skills_dir.is_dir():
            for skill_md in sorted(skills_dir.rglob("SKILL.md")):
                skill_name = skill_md.parent.name
                desc = ""
                task_type = "general"
                try:
                    content = skill_md.read_text()
                    desc = parse_frontmatter_field(content, "description") or ""
                    task_type = parse_frontmatter_field(content, "task_type") or "general"
                    if not desc:
                        has_frontmatter = content.startswith("---")
                        if has_frontmatter:
                            desc = first_content_line(content)
                        else:
                            for line in content.splitlines():
                                stripped = line.strip()
                                if stripped and not stripped.startswith("#"):
                                    desc = stripped[:200]
                                    break
                except OSError:
                    pass
                skills.append(
                    DiscoveredSkill(
                        name=skill_name,
                        description=desc or f"Kiro skill: {skill_name}",
                        source="kiro:skills",
                        task_type=task_type,
                    )
                )

        # Deduplicate MCPs
        seen: set[str] = set()
        deduped: list[DiscoveredMcp] = []
        for m in mcps:
            if m.name not in seen:
                deduped.append(m)
                seen.add(m.name)

        return ScanResult(mcps=deduped, skills=skills, hooks=hooks, agents=agents)

    def rewrite_agent_profile(self, content: dict, agent_id: str) -> dict:
        from observal_cli.cmd_pull import _rewrite_kiro_agent_profile

        return _rewrite_kiro_agent_profile(content, agent_id=agent_id)

    def rewrite_hooks(self, content: dict, agent_id: str) -> dict:
        """Refresh the standalone v1 hooks file.

        ``agent_id`` is accepted for protocol compatibility and deliberately
        unused: one hooks file serves every Kiro agent in the scope, and Kiro
        attribution comes from session metadata, not the hook environment.
        """
        from observal_cli.harness_specs.kiro_hooks_spec import merge_kiro_hooks_file

        return merge_kiro_hooks_file(content)

    def patch_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _patch_kiro

        return _patch_kiro(dry_run)

    def cleanup_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _cleanup_kiro

        return _cleanup_kiro(dry_run)

    def requires_explicit_agent_id(self) -> bool:
        return True


register_adapter(KiroAdapter())
