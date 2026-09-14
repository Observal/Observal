# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 EuanTop <euan@mail.bnu.edu.cn>
# SPDX-License-Identifier: Apache-2.0

"""Pi harness adapter for scanning and hook detection."""

from __future__ import annotations

import json
from pathlib import Path

from observal_cli.discovery.adapter_support import RichAdapterScanner
from observal_cli.discovery.models import AdapterDiscoveryResult, DiagnosticCode, DiscoveryScope
from observal_cli.discovery.redact import redact_text, redact_value
from observal_cli.harness import (
    BundledSkillPlan,
    DiscoveredHook,
    DiscoveredMcp,
    DiscoveredSkill,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.harness.base import BaseAdapter
from observal_cli.shared.utils import extract_mcp_servers, first_content_line, parse_frontmatter_field


class PiAdapter(BaseAdapter):
    """Adapter for Pi.

    Pi is harness-centric: the entirety of pi IS one agent.
    MCP servers are managed via pi-mcp-adapter (reads ~/.pi/agent/mcp.json).
    Hooks are delivered as the observal-pi package.
    """

    home_markers = (".pi",)
    managed_agent_profiles = ("user:AGENTS.md",)
    managed_skills = ("user:skills/{name}/SKILL.md",)

    @property
    def harness_name(self) -> str:
        return "pi"

    def plan_bundled_skill_install(
        self,
        skill_name: str,
        home: Path,
        installed_harnesses: frozenset[str],
    ) -> BundledSkillPlan:
        """Share bundled skills with Codex instead of creating Pi duplicates."""
        native = home / ".pi" / "agent" / "skills" / skill_name / "SKILL.md"
        shared = home / ".agents" / "skills" / skill_name / "SKILL.md"
        return BundledSkillPlan(
            target=shared if "codex" in installed_harnesses else native,
            reuse_candidates=(shared,),
            cleanup_candidates=(native,),
        )

    # ── Scanning ──────────────────────────────────────────────

    def scan_home(self, home: Path | None = None) -> ScanResult:
        """Discover MCPs from ~/.pi/agent/mcp.json, skills from ~/.pi/agent/skills/."""
        home = home or Path.home()
        pi_dir = home / ".pi" / "agent"
        if not pi_dir.exists():
            return ScanResult()

        mcps = self._scan_mcps(pi_dir / "mcp.json", "pi:global")
        skills = self._scan_skills(pi_dir / "skills")
        return ScanResult(mcps=mcps, skills=skills)

    def scan_project(self, project_dir: Path) -> ScanResult:
        """Discover MCPs from .pi/mcp.json, skills from .pi/skills/."""
        pi_dir = project_dir / ".pi"
        if not pi_dir.exists():
            return ScanResult()

        mcps = self._scan_mcps(pi_dir / "mcp.json", "pi:project")
        skills = self._scan_skills(pi_dir / "skills")
        return ScanResult(mcps=mcps, skills=skills)

    def discover_home(self, home: Path | None = None) -> AdapterDiscoveryResult:
        home = home or Path.home()
        return self._discover_pi_root(home / ".pi" / "agent", DiscoveryScope.USER, home=home)

    def discover_project(self, project_dir: Path) -> AdapterDiscoveryResult:
        return self._discover_pi_root(
            project_dir / ".pi",
            DiscoveryScope.PROJECT,
            project_dir=project_dir,
            agent_file=project_dir / "AGENTS.md",
        )

    def _discover_pi_root(
        self,
        root: Path,
        scope: DiscoveryScope,
        *,
        home: Path | None = None,
        project_dir: Path | None = None,
        agent_file: Path | None = None,
    ) -> AdapterDiscoveryResult:
        # Project AGENTS.md sits one level above .pi, so the approved project
        # root must include both documented sources.
        approved_root = project_dir if project_dir is not None else root
        scanner = RichAdapterScanner(
            harness=self.harness_name,
            scope=scope,
            root=approved_root,
            home=home,
            project_dir=project_dir,
        )
        source = "pi:global" if scope is DiscoveryScope.USER else "pi:project"
        scanner.add_mcp_config(root / "mcp.json", source=source, description_prefix="Pi MCP")
        scanner.add_skills(root / "skills", source="pi:skills", prefix="Pi skill")
        scanner.add_agent_document(agent_file or (root / "AGENTS.md"), name="pi-agent")

        settings_path = root / "settings.json"
        settings = scanner.read_json(settings_path)
        if settings is not None:
            extensions = settings.get("extensions", [])
            if not isinstance(extensions, list):
                scanner.diagnostic(
                    DiagnosticCode.METADATA_MALFORMED,
                    settings_path,
                    "Pi extensions setting must be an array",
                )
            else:
                for index, value in enumerate(extensions):
                    if not isinstance(value, str):
                        continue
                    extension_name = Path(value.removeprefix("+").removeprefix("-")).stem
                    if extension_name in {"observal", "observal-pi"} or "observal-pi" in value:
                        continue
                    safe_value = redact_text(Path(value.removeprefix("+").removeprefix("-")).name)
                    scanner.add_component(
                        DiscoveredHook(
                            name=redact_text(extension_name or f"extension-{index + 1}"),
                            event="extension",
                            handler_type="extension",
                            handler_config=redact_value({"extension": safe_value}),
                            description=f"Pi extension: {redact_text(extension_name)}",
                            source=source,
                        ),
                        settings_path,
                    )
        return scanner.finish()

    # ── Hook detection ────────────────────────────────────────

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=[],
            format="extension",
            markers=["observal-pi"],
        )

    def detect_hooks(self, config_dir: Path) -> str:
        """Check for the user-global Observal TypeScript extension."""
        return "installed" if (config_dir / "extensions" / "observal.ts").is_file() else "missing"

    def _scan_mcps(self, mcp_file: Path, source: str) -> list[DiscoveredMcp]:
        if not mcp_file.exists():
            return []
        try:
            data = json.loads(mcp_file.read_text())
            servers = extract_mcp_servers(data)
            return [
                DiscoveredMcp(
                    name=name,
                    command=cfg.get("command"),
                    args=cfg.get("args", []),
                    url=cfg.get("url"),
                    description=f"Pi MCP: {name}",
                    source=source,
                )
                for name, cfg in servers.items()
                if isinstance(cfg, dict)
            ]
        except (json.JSONDecodeError, OSError):
            return []

    def _scan_skills(self, skills_dir: Path) -> list[DiscoveredSkill]:
        if not skills_dir.is_dir():
            return []
        skills = []
        for skill_md in sorted(skills_dir.rglob("SKILL.md")):
            name = skill_md.parent.name
            desc = ""
            try:
                content = skill_md.read_text()
                desc = parse_frontmatter_field(content, "description") or ""
                if not desc:
                    desc = first_content_line(content)
            except OSError:
                pass
            skills.append(
                DiscoveredSkill(
                    name=name,
                    description=desc or f"Skill: {name}",
                    source="pi:skills",
                )
            )
        return skills

    def persist_active_agent(self, agent_id: str, name: str, version: str | None) -> None:
        from observal_cli.config import load, save

        config = load()
        config["active_agent"] = {"id": agent_id, "name": name, "version": version}
        save(config)

    def patch_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _patch_pi

        return _patch_pi(dry_run)

    def cleanup_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _cleanup_pi

        return _cleanup_pi(dry_run)


register_adapter(PiAdapter())
