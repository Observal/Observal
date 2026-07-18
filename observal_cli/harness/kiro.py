# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Kiro harness adapter."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
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


class KiroAdapter(BaseAdapter):
    """Adapter for Kiro (AWS)."""

    home_markers = (".kiro",)
    managed_agent_profiles = ("user:agents/{name}.json", "project:.kiro/agents/{name}.json")
    managed_skills = ("user:skills/{name}/SKILL.md",)

    @property
    def harness_name(self) -> str:
        return "kiro"

    def resolve_session_source(self, event: dict[str, Any], home: Path | None = None) -> SessionSource | None:
        from observal_cli.sessions.kiro import find_kiro_jsonl, resolve_session_id

        home = home or Path.home()
        cwd = str(event.get("cwd") or "")
        explicit_id = str(
            event.get("session_id") or event.get("conversation_id") or event.get("conversationId") or ""
        )
        sqlite_source = self._sqlite_source(home, session_id=explicit_id, cwd=cwd)
        if sqlite_source is not None:
            self._persist_session_id(home, sqlite_source.session_id)
            return sqlite_source

        session_id = explicit_id or resolve_session_id(event, home=home)
        if not session_id:
            return None
        path = find_kiro_jsonl(session_id, home=home)
        if path is None:
            return None
        self._persist_session_id(home, session_id)
        return SessionSource(self.harness_name, session_id, path, cwd=cwd)

    def discover_session_sources(
        self,
        home: Path | None = None,
        since_hours: int = 168,
    ) -> list[SessionSource]:
        from observal_cli.sessions.kiro import find_sessions_dir

        home = home or Path.home()
        cutoff = time.time() - since_hours * 3600
        sources = {source.session_id: source for source in self._sqlite_sources(home, cutoff)}
        root = find_sessions_dir(home)
        if root.is_dir():
            for path in sorted(root.glob("*.jsonl")):
                try:
                    if path.stat().st_mtime >= cutoff and path.stem not in sources:
                        sources[path.stem] = SessionSource(self.harness_name, path.stem, path)
                except OSError:
                    continue
        return sorted(sources.values(), key=lambda source: source.modified_at or 0, reverse=True)

    def session_extra_fields(
        self,
        source: SessionSource,
        event: dict[str, Any],
        final: bool,
        home: Path | None = None,
    ) -> dict[str, Any]:
        from observal_cli.sessions.kiro import read_kiro_credits

        home = home or Path.home()
        attempts = 5 if final else 1
        for attempt in range(attempts):
            credits = self._sqlite_credits(home, source.session_id)
            if credits is None:
                credits = read_kiro_credits(source.session_id, home=home)
            if credits is not None:
                return {"total_credits": credits}
            if attempt < attempts - 1:
                time.sleep(0.5 * (attempt + 1))
        return {}

    @staticmethod
    def _persist_session_id(home: Path, session_id: str) -> None:
        state_dir = home / ".observal"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / ".kiro-session").write_text(json.dumps({"session_id": session_id}))

    @staticmethod
    def _sqlite_path(home: Path) -> Path | None:
        candidates = (
            home / ".local" / "share" / "kiro-cli" / "data.sqlite3",
            home / "Library" / "Application Support" / "kiro-cli" / "data.sqlite3",
            home / "AppData" / "Local" / "kiro-cli" / "data.sqlite3",
        )
        return next((path for path in candidates if path.is_file()), None)

    def _sqlite_source(self, home: Path, session_id: str = "", cwd: str = "") -> SessionSource | None:
        path = self._sqlite_path(home)
        if path is None:
            return None
        where = "conversation_id = ?" if session_id else "key = ?"
        value = session_id or cwd
        if not value:
            return None
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as connection:
                row = connection.execute(
                    f"SELECT conversation_id, value, updated_at FROM conversations_v2 "
                    f"WHERE {where} ORDER BY updated_at DESC LIMIT 1",
                    (value,),
                ).fetchone()
        except sqlite3.Error:
            return None
        return self._source_from_sqlite_row(row, cwd) if row else None

    def _sqlite_sources(self, home: Path, cutoff: float) -> list[SessionSource]:
        path = self._sqlite_path(home)
        if path is None:
            return []
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as connection:
                rows = connection.execute(
                    "SELECT conversation_id, value, updated_at, key FROM conversations_v2 "
                    "WHERE updated_at >= ? ORDER BY updated_at DESC",
                    (int(cutoff * 1000),),
                ).fetchall()
        except sqlite3.Error:
            return []
        sources: list[SessionSource] = []
        for session_id, raw, updated_at, cwd in rows:
            source = self._source_from_sqlite_row((session_id, raw, updated_at), cwd)
            if source is not None:
                sources.append(source)
        return sources

    def _source_from_sqlite_row(self, row: tuple, cwd: str) -> SessionSource | None:
        session_id, raw, updated_at = row
        # ponytail: Kiro stores a conversation as one JSON blob; use row-level reads if its schema exposes them.
        try:
            conversation = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None
        records = tuple(self._conversation_records(conversation))
        return SessionSource(
            self.harness_name,
            str(session_id),
            cwd=cwd,
            records=records,
            modified_at=float(updated_at) / 1000,
        )

    def _sqlite_credits(self, home: Path, session_id: str) -> float | None:
        path = self._sqlite_path(home)
        if path is None:
            return None
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as connection:
                row = connection.execute(
                    "SELECT value FROM conversations_v2 WHERE conversation_id = ? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
            conversation = json.loads(row[0]) if row else {}
        except (sqlite3.Error, TypeError, json.JSONDecodeError):
            return None
        usage = conversation.get("user_turn_metadata", {}).get("usage_info", [])
        total = sum(float(item.get("value") or 0) for item in usage if item.get("unit") == "credit")
        return total or None

    @classmethod
    def _conversation_records(cls, conversation: dict) -> list[str]:
        records: list[str] = []
        for turn in conversation.get("history", []):
            if not isinstance(turn, dict):
                continue
            metadata = turn.get("request_metadata") if isinstance(turn.get("request_metadata"), dict) else {}
            user_record = cls._user_record(turn.get("user"), metadata)
            assistant_record = cls._assistant_record(turn.get("assistant"), metadata)
            if user_record:
                records.append(json.dumps(user_record, sort_keys=True, separators=(",", ":")))
            if assistant_record:
                records.append(json.dumps(assistant_record, sort_keys=True, separators=(",", ":")))
        return records

    @classmethod
    def _user_record(cls, user: object, metadata: dict) -> dict | None:
        if not isinstance(user, dict) or not isinstance(user.get("content"), dict):
            return None
        content = user["content"]
        if isinstance(content.get("Prompt"), dict):
            prompt = str(content["Prompt"].get("prompt") or "")
            return {
                "version": "v2",
                "kind": "Prompt",
                "data": {
                    "message_id": str(metadata.get("message_id") or ""),
                    "content": [{"kind": "text", "data": prompt}],
                    "meta": {"timestamp": cls._timestamp_seconds(user, metadata)},
                },
            }
        result_group = content.get("ToolUseResults") or content.get("CancelledToolUses")
        if not isinstance(result_group, dict):
            return None
        results = result_group.get("tool_use_results", [])
        return {
            "version": "v2",
            "kind": "ToolResults",
            "data": {
                "content": [
                    {
                        "kind": "toolResult",
                        "data": {
                            "toolUseId": str(result.get("tool_use_id") or ""),
                            "status": str(result.get("status") or "success").lower(),
                            "content": cls._result_content(result.get("content")),
                        },
                    }
                    for result in results
                    if isinstance(result, dict)
                ]
            },
        }

    @staticmethod
    def _assistant_record(assistant: object, metadata: dict) -> dict | None:
        if not isinstance(assistant, dict):
            return None
        response = assistant.get("Response")
        if isinstance(response, dict):
            content = [{"kind": "text", "data": str(response.get("content") or "")}]
            message_id = response.get("message_id")
        else:
            tool_use = assistant.get("ToolUse")
            if not isinstance(tool_use, dict):
                return None
            content = []
            if tool_use.get("content"):
                content.append({"kind": "text", "data": str(tool_use["content"])})
            content.extend(
                {
                    "kind": "toolUse",
                    "data": {
                        "toolUseId": str(item.get("id") or ""),
                        "name": str(item.get("name") or ""),
                        "input": item.get("args") if isinstance(item.get("args"), dict) else {},
                    },
                }
                for item in tool_use.get("tool_uses", [])
                if isinstance(item, dict)
            )
            message_id = tool_use.get("message_id")
        return {
            "version": "v2",
            "kind": "AssistantMessage",
            "data": {"message_id": str(message_id or metadata.get("message_id") or ""), "content": content},
        }

    @staticmethod
    def _timestamp_seconds(user: dict, metadata: dict) -> float:
        timestamp_ms = metadata.get("request_start_timestamp_ms")
        if timestamp_ms:
            return float(timestamp_ms) / 1000
        raw = user.get("timestamp")
        if raw:
            try:
                return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        return 0.0

    @staticmethod
    def _result_content(content: object) -> list[dict]:
        if not isinstance(content, list):
            return []
        result: list[dict] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if "Text" in item:
                result.append({"kind": "text", "data": str(item["Text"])})
            else:
                result.append({"kind": "json", "data": item})
        return result

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

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)

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


register_adapter(KiroAdapter())
