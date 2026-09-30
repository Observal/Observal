# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""DeepSeek Harness: native user Cordis patches, on-demand skills and session hooks."""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from observal_cli import deepseek_plugin
from observal_cli.harness import (
    DiscoveredMcp,
    DiscoveredSkill,
    HookSpec,
    ScanResult,
    SessionSource,
    register_adapter,
)
from observal_cli.harness.base import BaseAdapter
from observal_cli.harness.protocol import BundledSkillPlan
from observal_cli.harness_specs.deepseek_hooks_spec import EVENTS, is_session_push_command
from observal_cli.sessions.deepseek import resolve_dsh_home
from observal_cli.shared.deepseek_config import (
    HOOK_ID,
    MCP_NAME,
    TELEMETRY_ID,
    edit_owned_rows,
    read_entries,
)
from observal_cli.shared.utils import atomic_write, parse_frontmatter_field, sanitize_name


def _inserted_ids(patches: list[dict]) -> set[str]:
    """IDs of the plugin rows a generated Cordis patch list inserts."""
    return {row.get("id") for patch in patches for row in patch.get("insert", []) if isinstance(row, dict)}


class DeepSeekAdapter(BaseAdapter):
    """Scan only literal patches; dynamic Cordis configuration is not evaluated."""

    managed_agent_profiles = (
        "user:skills/observal-{name}/SKILL.md",
        "project:.dsh/skills/observal-{name}/SKILL.md",
    )
    managed_skills = ("user:skills/{name}/SKILL.md", "project:.dsh/skills/{name}/SKILL.md")
    managed_mcp_files = ("user:cordis.patch.yml",)

    @property
    def harness_name(self) -> str:
        return "deepseek"

    def resolve_home_dir(self) -> Path:
        return resolve_dsh_home()

    def is_installed(self, home: Path | None = None) -> bool:
        root = resolve_dsh_home(home)
        return root.is_dir() or root.is_file()

    def plan_bundled_skill_install(
        self, skill_name: str, home: Path, installed_harnesses: frozenset[str]
    ) -> BundledSkillPlan:
        return BundledSkillPlan(resolve_dsh_home(home) / "skills" / sanitize_name(skill_name) / "SKILL.md")

    def install_notes(self, is_user_scope: bool) -> tuple[str, ...]:
        return (
            "DeepSeek MCPs and hooks are activated from the user DSH_HOME patch for every profile, "
            "even when agent skills are project-local. Invoke the agent skill explicitly; it is not auto-selected.",
        )

    def skill_install_destination(self, name: str, scope: str, cwd: Path) -> Path:
        root = resolve_dsh_home() if scope == "user" else cwd / ".dsh"
        return root / "skills" / sanitize_name(name)

    def resolve_install_path(self, raw_path: str, target_dir: Path, *, allow_home: bool = False) -> Path:
        """Route only known generated user paths to runtime DSH_HOME, in either scope."""
        from observal_cli.cmd_pull import _resolve_path

        owned = ("~/.dsh/cordis.patch.yml", "~/.dsh/observal/hooks.json")
        if raw_path in owned:
            return resolve_dsh_home() / raw_path.removeprefix("~/.dsh/")
        if raw_path.startswith(("~/.dsh/skills/", "~/.dsh/observal/scripts/")):
            tail = raw_path.removeprefix("~/.dsh/")
            if "\\" in tail or any(part in ("", ".", "..") for part in tail.split("/")):
                raise ValueError("unsafe DeepSeek generated path")
            root = resolve_dsh_home()
            destination = root / tail
            if not destination.resolve().is_relative_to(root.resolve()):
                raise ValueError("DeepSeek generated path escapes DSH_HOME")
            return destination
        if raw_path.startswith("~/.dsh/") or raw_path.startswith(".dsh/"):
            parts = Path(raw_path.replace("~/.dsh/", ".dsh/", 1)).parts
            if any(part == ".." for part in parts) or "\\" in raw_path:
                raise ValueError("unsafe DeepSeek generated path")
        return _resolve_path(raw_path, target_dir, allow_home=allow_home)

    def write_mcp_config(self, path: Path, content: Any) -> str:
        """Merge only the stable IDs in a generated patch, retaining other patch source."""
        if path != resolve_dsh_home() / "cordis.patch.yml":
            raise ValueError("DeepSeek MCP patches must be installed at the runtime DSH_HOME")
        if not isinstance(content, list):
            raise ValueError("DeepSeek MCP content must be a Cordis patch list")
        existed = path.exists()
        patches = self._resolve_bridge_path(content, path.parent)
        ids = _inserted_ids(patches)
        if TELEMETRY_ID not in ids:
            patches.append({"insert": [self._collector_row(path.parent)]})
        required = bool(self._clean_hooks(path.parent).get("hooks")) or HOOK_ID in ids
        if required and HOOK_ID not in ids:
            patches.append({"insert": [self._bridge_row(path.parent)]})
        self._sync_telemetry(path.parent, patches, set() if required else {HOOK_ID}, remove=False)
        return "merged" if existed else "created"

    def write_hook_config(self, path: Path, content: Any, *, merge: bool = False) -> str:
        if path != resolve_dsh_home() / "observal" / "hooks.json":
            raise ValueError("DeepSeek hooks must be installed at the runtime DSH_HOME")
        if not isinstance(content, dict) or not isinstance(content.get("hooks"), dict):
            raise ValueError("DeepSeek hooks must contain event rules")
        existed = path.exists()
        previous = json.loads(path.read_text(encoding="utf-8")) if existed else {}
        desired = self._merge_hooks(previous, content)
        if desired != previous:
            atomic_write(path, json.dumps(desired, indent=2) + "\n")
        return "merged" if existed else "created"

    @staticmethod
    def _bridge_row(home: Path) -> dict:
        return {
            "id": HOOK_ID,
            "name": "@deepseek-ai/dsh-hooks-claude-code",
            "config": {"configPath": str(home / "observal" / "hooks.json")},
        }

    @staticmethod
    def _collector_row(home: Path) -> dict:
        return {
            "id": TELEMETRY_ID,
            "name": str(deepseek_plugin.plugin_path(home)),
            "config": {"pythonPath": sys.executable, "dshHome": str(home)},
        }

    @staticmethod
    def _clean_hooks(root: Path) -> dict:
        """Hooks.json with obsolete Observal session-push handlers stripped."""
        hooks = root / "observal" / "hooks.json"
        previous = json.loads(hooks.read_text()) if hooks.is_file() else {}
        return DeepSeekAdapter._merge_hooks(previous, {"hooks": {}})

    def _sync_telemetry(
        self, root: Path, incoming: list[dict], target_ids: set[str], *, remove: bool, dry_run: bool = False
    ) -> bool:
        """Bring the owned patch rows, cleaned hooks, and plugin file to one state.

        Pull, doctor patch, and doctor cleanup differ only in the rows they
        request and whether the plugin is installed or removed; the read-edit-
        write sequence and the fail-closed ordering are shared.
        """
        from observal_cli.cmd_pull import _atomic_write_text

        patch = root / "cordis.patch.yml"
        hooks = root / "observal" / "hooks.json"
        current = patch.read_text(encoding="utf-8") if patch.is_file() else ""
        previous = json.loads(hooks.read_text()) if hooks.is_file() else {}
        desired = self._merge_hooks(previous, {"hooks": {}})
        updated = edit_owned_rows(current, incoming, target_ids=target_ids)
        stale = {"current", "stale"} if remove else {"missing", "stale", "unmanaged"}
        changed = updated != current or desired != previous or deepseek_plugin.status(root) in stale
        if not changed or dry_run:
            return changed
        if not remove:
            deepseek_plugin.install(home=root)
        if updated != current:
            _atomic_write_text(patch, updated)
        if desired != previous:
            atomic_write(hooks, json.dumps(desired, indent=2) + "\n")
        if remove:
            deepseek_plugin.remove(home=root)
        return changed

    @staticmethod
    def _row_installed(entries: list[dict], row: dict) -> bool:
        """Whether an owned plugin row is present, enabled, and exactly as generated."""
        return any(
            entry.get("id") == row["id"]
            and entry.get("name") == row["name"]
            and entry.get("config") == row["config"]
            and entry.get("disabled") is not True
            for entry in entries
        )

    @staticmethod
    def _resolve_bridge_path(content: list[dict], home: Path) -> list[dict]:
        """Resolve generated Cordis paths and interpreter without changing foreign rows."""
        import copy

        patches = copy.deepcopy(content)
        for patch in patches:
            if not isinstance(patch, dict) or not isinstance(patch.get("insert"), list):
                raise ValueError("invalid DeepSeek patch")
            for row in patch["insert"]:
                if not isinstance(row, dict):
                    raise ValueError("invalid DeepSeek plugin")
                if row.get("id") == HOOK_ID:
                    config = row.get("config")
                    if not isinstance(config, dict) or config.get("configPath") != "~/.dsh/observal/hooks.json":
                        raise ValueError("invalid DeepSeek hook bridge path")
                    config["configPath"] = str(home / "observal" / "hooks.json")
                elif row.get("id") == TELEMETRY_ID:
                    if row.get("name") != "~/.dsh/observal/collector.mjs" or row.get("config") != {
                        "pythonPath": "<runtime-python>",
                        "dshHome": "<runtime-dsh-home>",
                    }:
                        raise ValueError("invalid DeepSeek collector placeholder")
                    row.update(DeepSeekAdapter._collector_row(home))
        return patches

    def extract_mcp_servers(self, config: dict | list) -> dict:
        """Return plugin entries for capability-lock recording, never a fake mcpServers map."""
        patches = config.get("content", []) if isinstance(config, dict) else config
        servers = {}
        if isinstance(patches, list):
            for patch in patches:
                if not isinstance(patch, dict):
                    continue
                for row in patch.get("insert", []):
                    if isinstance(row, dict) and row.get("name") == MCP_NAME:
                        entry = row.get("config")
                        if isinstance(entry, dict) and isinstance(entry.get("serverName"), str):
                            servers[entry["serverName"]] = entry
        return servers

    def resolve_session_source(self, event: dict[str, Any], home: Path | None = None) -> SessionSource | None:
        from observal_cli.sessions.deepseek import resolve_session_source

        return resolve_session_source(event, home=home)

    def discover_session_sources(self, home: Path | None = None, since_hours: int = 168) -> list[SessionSource]:
        from observal_cli.sessions.deepseek import discover_session_sources

        return discover_session_sources(home=home, since_hours=since_hours)

    def related_session_sources(self, source: SessionSource, home: Path | None = None) -> list[SessionSource]:
        from observal_cli.sessions.deepseek import related_session_sources

        return related_session_sources(source, home=home)

    def resolve_session_agent_identity(
        self, session_jsonl: Path | None, cwd: str
    ) -> tuple[str | None, str | None] | None:
        """Attribute sessions through the observal-<agent> skill call in the log."""
        from observal_cli.sessions.deepseek import resolve_session_agent_identity

        return resolve_session_agent_identity(session_jsonl, cwd)

    def defer_session_delivery(self) -> bool:
        return True

    def is_session_final(self, event: dict[str, Any]) -> bool:
        """Stop and SubagentStop finish turns, not persistent DeepSeek sessions."""
        return False

    def scan_home(self, home: Path | None = None) -> ScanResult:
        root = resolve_dsh_home(home)
        result = ScanResult()
        for path, source in ((root / "cordis.patch.yml", "deepseek:user"),):
            self._scan_patch(path, source, result)
        profiles = root / "profiles"
        if profiles.is_dir():
            for path in sorted(profiles.glob("*/cordis.patch.yml")):
                self._scan_patch(path, f"deepseek:profile:{path.parent.name} (select with --profile)", result)
        result.skills.extend(self._skills(root / "skills", "deepseek:user"))
        result.skills.extend(self._skills((home or Path.home()) / ".agents" / "skills", "deepseek:user:.agents"))
        return result

    def scan_project(self, project_dir: Path) -> ScanResult:
        """Project patches require an explicit --patch; do not report them as active MCPs."""
        return ScanResult(
            skills=self._skills(project_dir / ".dsh" / "skills", "deepseek:project:.dsh")
            + self._skills(project_dir / ".agents" / "skills", "deepseek:project:.agents")
        )

    @staticmethod
    def _skills(root: Path, source: str) -> list[DiscoveredSkill]:
        if not root.is_dir():
            return []
        skills: list[DiscoveredSkill] = []
        candidates = sorted((*root.glob("*/SKILL.md"), *root.glob("*.md")))
        for path in candidates:
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeError, OSError):
                continue
            name = parse_frontmatter_field(content, "name")
            description = parse_frontmatter_field(content, "description")
            if not name or not description or name != (path.parent.name if path.name == "SKILL.md" else path.stem):
                continue
            skills.append(DiscoveredSkill(name, description, source))
        return skills

    @staticmethod
    def _scan_patch(path: Path, source: str, result: ScanResult) -> None:
        try:
            entries = read_entries(path)
        except (OSError, UnicodeError, ValueError):
            return
        for entry in entries:
            if entry.get("name") != MCP_NAME or entry.get("disabled") is True:
                continue
            config = entry.get("config")
            if (
                not isinstance(config, dict)
                or not isinstance(config.get("serverName"), str)
                or re.fullmatch(r"[A-Za-z0-9_-]{1,32}", config["serverName"]) is None
            ):
                continue
            transport = config.get("transport")
            if transport not in ("stdio", "streamable-http"):
                continue
            result.mcps.append(
                DiscoveredMcp(
                    config["serverName"],
                    config.get("command") if transport == "stdio" else None,
                    config.get("args") if transport == "stdio" and isinstance(config.get("args"), list) else [],
                    config.get("url") if transport == "streamable-http" else None,
                    f"DeepSeek {transport} MCP plugin",
                    source,
                )
            )

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(events=list(EVENTS), format="command", markers=[TELEMETRY_ID])

    def generate_hook_config(self, observal_url: str, api_key: str, agent_id: str | None = None) -> dict:
        """Telemetry uses the native plugin, not a command-hook JSON config."""
        return {"hooks": {}}

    def rewrite_hooks(self, content: dict, agent_id: str) -> dict:
        """Resolve generated commands to the local interpreter and runtime script paths."""
        import copy

        rewritten = copy.deepcopy(content)
        for rules in rewritten.get("hooks", {}).values():
            if isinstance(rules, list):
                for rule in rules:
                    if isinstance(rule, dict):
                        for handler in rule.get("hooks", []):
                            if not isinstance(handler, dict):
                                continue
                            command = handler.get("command")
                            if is_session_push_command(command):
                                raise ValueError("DeepSeek session-push command hooks are no longer supported")
                            if isinstance(command, str) and command.startswith("~/.dsh/observal/scripts/"):
                                path = self.resolve_install_path(command, Path.cwd())
                                handler["command"] = shlex.quote(str(path))
        return rewritten

    def detect_hooks(self, config_dir: Path) -> str:
        root = config_dir if config_dir.name == ".dsh" or config_dir == resolve_dsh_home() else resolve_dsh_home()
        patch = root / "cordis.patch.yml"
        hooks = root / "observal" / "hooks.json"
        try:
            entries = read_entries(patch)
            previous = json.loads(hooks.read_text()) if hooks.is_file() else {}
            desired = self._merge_hooks(previous, {"hooks": {}})
            collector = self._row_installed(entries, self._collector_row(root))
            bridge = self._row_installed(entries, self._bridge_row(root))
            healthy = (
                collector
                and deepseek_plugin.status(root) == "current"
                and previous == desired
                and bridge == bool(desired.get("hooks"))
            )
        except (OSError, ValueError, TypeError, AttributeError):
            return "partial" if patch.exists() or hooks.exists() else "missing"
        if healthy:
            return "installed"
        return "partial" if collector or patch.exists() or hooks.exists() else "missing"

    def patch_hooks(self, dry_run: bool) -> bool:
        root = resolve_dsh_home()
        required = bool(self._clean_hooks(root).get("hooks"))
        incoming = [{"insert": [self._collector_row(root)]}]
        if required:
            incoming.append({"insert": [self._bridge_row(root)]})
        return self._sync_telemetry(root, incoming, set() if required else {HOOK_ID}, remove=False, dry_run=dry_run)

    def cleanup_hooks(self, dry_run: bool) -> bool:
        root = resolve_dsh_home()
        ids = {TELEMETRY_ID}
        if not self._clean_hooks(root).get("hooks"):
            ids.add(HOOK_ID)
        return self._sync_telemetry(root, [], ids, remove=True, dry_run=dry_run)

    @staticmethod
    def _merge_hooks(previous: dict, desired: dict) -> dict:
        """Keep foreign event rules and handlers, replace only session-push handlers."""
        if not isinstance(previous, dict) or not isinstance(previous.get("hooks", {}), dict):
            raise ValueError("DeepSeek hooks JSON must contain an object of events")
        result = dict(previous)
        events = dict(previous.get("hooks", {}))
        for event in set(events) | set(desired["hooks"]):
            rules = events.get(event, [])
            if not isinstance(rules, list):
                raise ValueError("DeepSeek hooks event rules must be lists")
            kept = []
            for rule in rules:
                if not isinstance(rule, dict) or not isinstance(rule.get("hooks"), list):
                    raise ValueError("invalid DeepSeek hook rule")
                handlers = [
                    handler
                    for handler in rule["hooks"]
                    if not isinstance(handler, dict) or not is_session_push_command(handler.get("command"))
                ]
                if handlers:
                    kept.append({**rule, "hooks": handlers})
            for rule in desired["hooks"].get(event, []):
                if rule not in kept:
                    kept.append(rule)
            if kept:
                events[event] = kept
            else:
                events.pop(event, None)
        if events:
            result["hooks"] = events
        else:
            result.pop("hooks", None)
        return result


register_adapter(DeepSeekAdapter())
