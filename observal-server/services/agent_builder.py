"""Agent builder — composes resolved components into portable agent manifests.

Generates IDE-specific agent files from a ResolvedAgent:
- Claude Code: .claude/agents/<name>.md (markdown) + MCP JSON config
- Cursor: .cursor/rules/<name>.md (markdown) + .cursor/mcp.json
- Gemini CLI: GEMINI.md (markdown) + MCP JSON config
- Kiro: ~/.kiro/agents/<name>.json (JSON)
- VSCode: .vscode/rules/<name>.md + .vscode/mcp.json
- Codex: AGENTS.md (markdown)
- GitHub Copilot: .github/copilot-instructions.md (markdown)
- OpenCode: AGENTS.md (markdown) + opencode.json (MCP config)

"""

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from schemas.ide_registry import IDE_REGISTRY, get_valid_ides
from services.agent_config_generator import _wrap_kiro_prompt
from services.agent_resolver import ResolvedAgent, ResolvedComponent

logger = logging.getLogger(__name__)


# ── Manifest Pydantic Models ────────────────────────────────────────


class ManifestComponent(BaseModel):
    """A single component entry in the agent manifest."""

    name: str
    version: str
    git_url: str = ""
    description: str = ""
    order: int = 0
    git_ref: str | None = None
    config_override: dict | None = None
    # MCP-specific
    transport: str | None = None
    tools: dict | None = None
    # Skill-specific
    slash_command: str | None = None
    task_type: str | None = None
    # Hook-specific
    event: str | None = None
    execution_mode: str | None = None
    priority: int | None = None
    handler_type: str | None = None
    handler_config: dict | None = None
    # Prompt-specific
    template: str | None = None
    variables: list[str] | None = None
    # Sandbox-specific
    image: str | None = None
    runtime_type: str | None = None
    resource_limits: dict | None = None

    def model_dump_compact(self) -> dict:
        """Dump only non-None fields for clean manifest output."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class ManifestComponents(BaseModel):
    """All components grouped by type."""

    mcps: list[ManifestComponent] = Field(default_factory=list)
    skills: list[ManifestComponent] = Field(default_factory=list)
    hooks: list[ManifestComponent] = Field(default_factory=list)
    prompts: list[ManifestComponent] = Field(default_factory=list)
    sandboxes: list[ManifestComponent] = Field(default_factory=list)

    def model_dump_compact(self) -> dict:
        """Only include non-empty component lists."""
        result = {}
        for key, items in [
            ("mcps", self.mcps),
            ("skills", self.skills),
            ("hooks", self.hooks),
            ("prompts", self.prompts),
            ("sandboxes", self.sandboxes),
        ]:
            if items:
                result[key] = [c.model_dump_compact() for c in items]
        return result


class ManifestError(BaseModel):
    component_type: str
    component_id: str
    reason: str


class AgentManifest(BaseModel):
    """Portable agent manifest — the canonical representation of a composed agent."""

    name: str
    version: str
    prompt: str = ""
    description: str = ""
    model_name: str = ""
    components: ManifestComponents = Field(default_factory=ManifestComponents)
    errors: list[ManifestError] = Field(default_factory=list)

    def model_dump_compact(self) -> dict:
        """Clean manifest output (no empty lists, no None values)."""
        result: dict = {
            "name": self.name,
            "version": self.version,
            "components": self.components.model_dump_compact(),
        }
        if self.prompt:
            result["prompt"] = self.prompt
        if self.description:
            result["description"] = self.description
        if self.model_name:
            result["model_name"] = self.model_name
        if self.errors:
            result["errors"] = [e.model_dump() for e in self.errors]
        return result


class CompositionSummary(BaseModel):
    """Lightweight summary of agent composition for API responses."""

    agent_id: str
    agent_name: str
    agent_version: str
    resolved: bool
    component_counts: dict[str, int] = Field(default_factory=dict)
    components: dict[str, list[dict]] = Field(default_factory=dict)
    errors: list[ManifestError] = Field(default_factory=list)


# ── IDE Agent File Models ───────────────────────────────────────────


class AgentFile(BaseModel):
    """A single file to write for IDE agent installation."""

    path: str
    content: str | dict
    format: Literal["markdown", "json", "toml"] = "json"


class IdeAgentConfig(BaseModel):
    """Complete IDE-specific agent configuration output."""

    ide: str
    files: list[AgentFile] = Field(default_factory=list)
    mcp_servers: dict = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    setup_commands: list[list[str]] = Field(default_factory=list)


# ── Builder Functions ───────────────────────────────────────────────


def _resolved_to_manifest_component(comp: ResolvedComponent) -> ManifestComponent:
    """Convert a ResolvedComponent to a ManifestComponent."""
    kwargs: dict = {
        "name": comp.name,
        "version": comp.version,
        "git_url": comp.git_url,
        "description": comp.description,
        "order": comp.order_index,
    }
    if comp.git_ref:
        kwargs["git_ref"] = comp.git_ref
    if comp.config_override:
        kwargs["config_override"] = comp.config_override

    # Type-specific fields from extra
    if comp.component_type == "mcp":
        if comp.extra.get("transport"):
            kwargs["transport"] = comp.extra["transport"]
        if comp.extra.get("tools_schema"):
            kwargs["tools"] = comp.extra["tools_schema"]
    elif comp.component_type == "skill":
        if comp.extra.get("slash_command"):
            kwargs["slash_command"] = comp.extra["slash_command"]
        if comp.extra.get("task_type"):
            kwargs["task_type"] = comp.extra["task_type"]
    elif comp.component_type == "hook":
        kwargs["event"] = comp.extra.get("event", "")
        kwargs["execution_mode"] = comp.extra.get("execution_mode", "async")
        kwargs["priority"] = comp.extra.get("priority", 100)
        kwargs["handler_type"] = comp.extra.get("handler_type", "")
        kwargs["handler_config"] = comp.extra.get("handler_config", {})
    elif comp.component_type == "prompt":
        if comp.extra.get("template"):
            kwargs["template"] = comp.extra["template"]
        if comp.extra.get("variables"):
            kwargs["variables"] = comp.extra["variables"]
    elif comp.component_type == "sandbox":
        kwargs["image"] = comp.extra.get("image", "")
        kwargs["runtime_type"] = comp.extra.get("runtime_type", "")
        if comp.extra.get("resource_limits"):
            kwargs["resource_limits"] = comp.extra["resource_limits"]

    return ManifestComponent(**kwargs)


def build_agent_manifest(resolved: ResolvedAgent) -> dict:
    """Build a portable agent manifest from a fully resolved agent.

    Returns a clean dict with only populated fields.
    """
    type_map = {
        "mcp": "mcps",
        "skill": "skills",
        "hook": "hooks",
        "prompt": "prompts",
        "sandbox": "sandboxes",
    }

    grouped: dict[str, list[ManifestComponent]] = {}
    for ctype, key in type_map.items():
        typed = resolved.components_by_type(ctype)
        if typed:
            grouped[key] = [_resolved_to_manifest_component(c) for c in typed]

    manifest = AgentManifest(
        name=resolved.agent_name,
        version=resolved.agent_version,
        prompt=resolved.agent_prompt,
        description=resolved.agent_description,
        model_name=resolved.model_name,
        components=ManifestComponents(**grouped),
        errors=[
            ManifestError(
                component_type=e.component_type,
                component_id=str(e.component_id),
                reason=e.reason,
            )
            for e in resolved.errors
        ],
    )
    return manifest.model_dump_compact()


def build_composition_summary(resolved: ResolvedAgent) -> dict:
    """Build a lightweight summary of the agent's composition for API responses."""
    type_map = {
        "mcp": "mcps",
        "skill": "skills",
        "hook": "hooks",
        "prompt": "prompts",
        "sandbox": "sandboxes",
    }

    component_counts: dict[str, int] = {}
    components_by_key: dict[str, list[dict]] = {}

    for ctype, key in type_map.items():
        typed = resolved.components_by_type(ctype)
        if typed:
            component_counts[ctype] = len(typed)
            components_by_key[key] = [{"name": c.name, "version": c.version, "order": c.order_index} for c in typed]

    summary = CompositionSummary(
        agent_id=str(resolved.agent_id),
        agent_name=resolved.agent_name,
        agent_version=resolved.agent_version,
        resolved=resolved.ok,
        component_counts=component_counts,
        components=components_by_key,
        errors=[
            ManifestError(
                component_type=e.component_type,
                component_id=str(e.component_id),
                reason=e.reason,
            )
            for e in resolved.errors
        ],
    )
    return summary.model_dump(exclude_none=True)


# ── IDE Agent File Generation ──────────────────────────────────────

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _sanitize_name(name: str) -> str:
    if _SAFE_NAME_RE.match(name):
        return name
    return re.sub(r"[^a-zA-Z0-9_-]", "-", name)


def _build_mcp_entries(manifest: AgentManifest) -> dict:
    """Build MCP server config entries from manifest components."""
    entries = {}
    for mcp in manifest.components.mcps:
        shim_args = ["--mcp-id", mcp.name, "--", "python", "-m", mcp.name]
        entries[mcp.name] = {
            "command": "observal-shim",
            "args": shim_args,
            "env": {},
        }
    return entries


def _build_skill_files(manifest: AgentManifest, ide: str) -> list[AgentFile]:
    """Generate IDE-specific skill files from manifest skills."""
    ide_key = ide.replace("_", "-")
    spec = IDE_REGISTRY.get(ide_key, {})
    skill_paths = spec.get("skill_file")
    if not skill_paths:
        return []

    files: list[AgentFile] = []
    skill_format = spec.get("skill_format")
    for skill in manifest.components.skills:
        name = _sanitize_name(skill.name)
        desc = skill.description or ""
        path = next(iter(skill_paths.values())).format(name=name)

        if skill_format == "yaml_frontmatter":
            content = f"---\nname: {name}\n"
            if desc:
                content += f'description: "{desc}"\n'
            if skill.slash_command and ide_key == "claude-code":
                content += f"command: /{skill.slash_command}\n"
            content += f"---\n\n{desc}\n"
        else:
            content = f"---\ndescription: {desc}\nalwaysApply: false\n---\n\n# {name}\n\n{desc}\n"

        files.append(AgentFile(path=path, content=content, format="markdown"))

    return files


def _build_rules_markdown(manifest: AgentManifest) -> str:
    """Build markdown rules content from the agent manifest."""
    sections = []

    if manifest.prompt:
        sections.append(manifest.prompt)

    # Component summary sections
    if manifest.components.mcps:
        lines = ["## MCP Servers", ""]
        for mcp in manifest.components.mcps:
            desc = f" — {mcp.description}" if mcp.description else ""
            lines.append(f"- **{mcp.name}** v{mcp.version}{desc}")
        sections.append("\n".join(lines))

    if manifest.components.skills:
        lines = ["## Skills", ""]
        for skill in manifest.components.skills:
            cmd = f" (`/{skill.slash_command}`)" if skill.slash_command else ""
            desc = f" — {skill.description}" if skill.description else ""
            lines.append(f"- **{skill.name}** v{skill.version}{cmd}{desc}")
        sections.append("\n".join(lines))

    if manifest.components.hooks:
        lines = ["## Hooks", ""]
        for hook in manifest.components.hooks:
            lines.append(f"- **{hook.name}** on `{hook.event}` ({hook.execution_mode})")
        sections.append("\n".join(lines))

    if manifest.components.prompts:
        lines = ["## Prompts", ""]
        for prompt in manifest.components.prompts:
            lines.append(f"- **{prompt.name}** v{prompt.version}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _generate_claude_code(manifest: AgentManifest) -> IdeAgentConfig:
    """Generate Claude Code agent config (.claude/agents/<name>.md + MCP commands)."""
    safe_name = _sanitize_name(manifest.name)
    mcp_entries = _build_mcp_entries(manifest)
    rules_content = _build_rules_markdown(manifest)

    setup_commands = []
    for name, cfg in mcp_entries.items():
        cmd = cfg.get("command", "observal-shim")
        args = cfg.get("args", [])
        setup_commands.append(["claude", "mcp", "add", name, "--", cmd, *args])

    # Build Claude Code agent file with YAML frontmatter
    desc_line = (manifest.description or safe_name).replace("\n", " ").strip()
    frontmatter_lines = [
        "---",
        f"name: {safe_name}",
        f'description: "{desc_line}"',
    ]
    if mcp_entries:
        frontmatter_lines.append("mcpServers:")
        for mcp_name in mcp_entries:
            frontmatter_lines.append(f"  - {mcp_name}")
    frontmatter_lines.append("---")
    agent_content = "\n".join(frontmatter_lines) + "\n\n" + rules_content

    skill_files = _build_skill_files(manifest, "claude-code")

    env: dict[str, str] = {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
    }
    otlp_url = getattr(manifest, "_observal_url", "") or ""
    if otlp_url:
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = otlp_url

    return IdeAgentConfig(
        ide="claude-code",
        files=[
            AgentFile(
                path=f".claude/agents/{safe_name}.md",
                content=agent_content,
                format="markdown",
            ),
            *skill_files,
        ],
        mcp_servers=mcp_entries,
        env=env,
        setup_commands=setup_commands,
    )


def _generate_cursor(manifest: AgentManifest) -> IdeAgentConfig:
    """Generate Cursor agent config (.cursor/rules/<name>.md + .cursor/mcp.json)."""
    safe_name = _sanitize_name(manifest.name)
    mcp_entries = _build_mcp_entries(manifest)
    rules_content = _build_rules_markdown(manifest)

    skill_files = _build_skill_files(manifest, "cursor")

    return IdeAgentConfig(
        ide="cursor",
        files=[
            AgentFile(
                path=f".cursor/rules/{safe_name}.md",
                content=rules_content,
                format="markdown",
            ),
            AgentFile(
                path=".cursor/mcp.json",
                content={"mcpServers": mcp_entries},
                format="json",
            ),
            *skill_files,
        ],
        mcp_servers=mcp_entries,
    )


def _generate_vscode(manifest: AgentManifest) -> IdeAgentConfig:
    """Generate VS Code agent config (.vscode/rules/<name>.md + .vscode/mcp.json)."""
    safe_name = _sanitize_name(manifest.name)
    mcp_entries = _build_mcp_entries(manifest)
    rules_content = _build_rules_markdown(manifest)

    skill_files = _build_skill_files(manifest, "vscode")

    return IdeAgentConfig(
        ide="vscode",
        files=[
            AgentFile(
                path=f".vscode/rules/{safe_name}.md",
                content=rules_content,
                format="markdown",
            ),
            AgentFile(
                path=".vscode/mcp.json",
                content={"servers": mcp_entries},
                format="json",
            ),
            *skill_files,
        ],
        mcp_servers=mcp_entries,
    )


def _generate_gemini_cli(manifest: AgentManifest) -> IdeAgentConfig:
    """Generate Gemini CLI agent config (GEMINI.md + .gemini/settings.json)."""
    mcp_entries = _build_mcp_entries(manifest)
    rules_content = _build_rules_markdown(manifest)
    otlp_url = getattr(manifest, "_observal_url", "") or ""

    settings: dict = {
        "telemetry": {
            "enabled": False,
            "logPrompts": True,
        },
    }
    if mcp_entries:
        settings["mcpServers"] = mcp_entries

    env: dict[str, str] = {
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
    }
    if otlp_url:
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = otlp_url

    return IdeAgentConfig(
        ide="gemini-cli",
        files=[
            AgentFile(
                path="GEMINI.md",
                content=rules_content,
                format="markdown",
            ),
            AgentFile(
                path=".gemini/settings.json",
                content=settings,
                format="json",
            ),
        ],
        mcp_servers=mcp_entries,
        env=env,
    )


_KIRO_EVENT_MAP = {
    "SessionStart": "agentSpawn",
    "UserPromptSubmit": "userPromptSubmit",
    "PreToolUse": "preToolUse",
    "PostToolUse": "postToolUse",
    "Stop": "stop",
}


def _build_kiro_hooks(safe_name: str, observal_url: str, platform: str = "") -> dict:
    """Build Kiro hook commands for telemetry collection."""
    if not observal_url:
        return {}
    hooks_path = f"{observal_url}/api/v1/telemetry/hooks"
    py = "python" if platform == "win32" else "python3"
    hook_cmd = f"{py} -m observal_cli.hooks.kiro_hook --url {hooks_path} --agent-name {safe_name}"
    stop_cmd = f"{py} -m observal_cli.hooks.kiro_stop_hook --url {hooks_path} --agent-name {safe_name}"
    return {
        "agentSpawn": [{"command": hook_cmd}],
        "userPromptSubmit": [{"command": hook_cmd}],
        "preToolUse": [{"matcher": "*", "command": hook_cmd}],
        "postToolUse": [{"matcher": "*", "command": hook_cmd}],
        "stop": [{"command": stop_cmd}],
    }


def _materialize_kiro_hook_components(hooks_dict: dict, manifest: AgentManifest) -> None:
    """Merge hook components from the agent manifest into the Kiro hooks dict."""
    for hook in manifest.components.hooks:
        if not hook.event or not hook.handler_config:
            continue
        kiro_event = _KIRO_EVENT_MAP.get(hook.event, hook.event)
        handler_type = hook.handler_type or "command"
        if handler_type == "command":
            cmd = hook.handler_config.get("command", "")
            if not cmd:
                continue
            entry: dict = {"command": cmd}
            if kiro_event in ("preToolUse", "postToolUse"):
                entry["matcher"] = hook.handler_config.get("matcher", "*")
            hooks_dict.setdefault(kiro_event, []).append(entry)
        elif handler_type == "http":
            url = hook.handler_config.get("url", "")
            if not url:
                continue
            entry = {"command": f"curl -s -X POST -H 'Content-Type: application/json' -d @- {url}"}
            if kiro_event in ("preToolUse", "postToolUse"):
                entry["matcher"] = hook.handler_config.get("matcher", "*")
            hooks_dict.setdefault(kiro_event, []).append(entry)


def _generate_kiro(manifest: AgentManifest) -> IdeAgentConfig:
    """Generate Kiro agent config (~/.kiro/agents/<name>.json)."""
    safe_name = _sanitize_name(manifest.name)
    mcp_entries = _build_mcp_entries(manifest)
    observal_url = getattr(manifest, "_observal_url", "") or ""
    platform = getattr(manifest, "_platform", "") or ""

    kiro_agent = {
        "name": safe_name,
        "description": manifest.description[:200] if manifest.description else "",
        "prompt": _wrap_kiro_prompt(manifest.prompt, safe_name),
        "mcpServers": mcp_entries,
        "tools": ["*"],
        "toolAliases": {},
        "allowedTools": [],
        "resources": [
            "file://AGENTS.md",
            "file://README.md",
            "skill://.kiro/skills/*/SKILL.md",
            "skill://~/.kiro/skills/*/SKILL.md",
        ],
        "hooks": _build_kiro_hooks(safe_name, observal_url, platform),
        "toolsSettings": {},
        "includeMcpJson": True,
        "model": None,
    }

    # Materialize hook components from the agent manifest into the hooks dict
    _materialize_kiro_hook_components(kiro_agent["hooks"], manifest)

    skill_files = _build_skill_files(manifest, "kiro")

    return IdeAgentConfig(
        ide="kiro",
        files=[
            AgentFile(
                path=f"~/.kiro/agents/{safe_name}.json",
                content=kiro_agent,
                format="json",
            ),
            *skill_files,
        ],
        mcp_servers=mcp_entries,
    )


def _generate_codex(manifest: AgentManifest) -> IdeAgentConfig:
    """Generate Codex agent config (AGENTS.md + ~/.codex/config.toml)."""
    rules_content = _build_rules_markdown(manifest)
    otlp_url = getattr(manifest, "_observal_url", "") or ""

    files = [
        AgentFile(
            path="AGENTS.md",
            content=rules_content,
            format="markdown",
        ),
    ]

    if otlp_url:
        toml_snippet = (
            "[otel]\n"
            'environment = "production"\n'
            "log_user_prompt = true\n"
            "\n"
            "[otel.exporter.otlp-http]\n"
            f'endpoint = "{otlp_url}/v1/logs"\n'
            'protocol = "http"\n'
            "\n"
            "[otel.trace_exporter.otlp-http]\n"
            f'endpoint = "{otlp_url}/v1/traces"\n'
            'protocol = "http"\n'
        )
        files.append(
            AgentFile(
                path="~/.codex/config.toml",
                content=toml_snippet,
                format="toml",
            ),
        )

    return IdeAgentConfig(
        ide="codex",
        files=files,
    )


def _generate_copilot(manifest: AgentManifest) -> IdeAgentConfig:
    """Generate GitHub Copilot agent config (.github/copilot-instructions.md + .vscode/mcp.json)."""
    mcp_entries = _build_mcp_entries(manifest)
    rules_content = _build_rules_markdown(manifest)

    files = [
        AgentFile(
            path=".github/copilot-instructions.md",
            content=rules_content,
            format="markdown",
        ),
    ]

    if mcp_entries:
        copilot_mcp_entries = {}
        for k, v in mcp_entries.items():
            copilot_mcp_entries[k] = {"type": "stdio", "command": v["command"], "args": v.get("args", [])}
            if v.get("env"):
                copilot_mcp_entries[k]["env"] = v["env"]
        files.append(
            AgentFile(
                path=".vscode/mcp.json",
                content={"servers": copilot_mcp_entries},
                format="json",
            ),
        )

    return IdeAgentConfig(
        ide="copilot",
        files=files,
        mcp_servers=mcp_entries,
    )


def _generate_opencode(manifest: AgentManifest) -> IdeAgentConfig:
    """Generate OpenCode agent config (AGENTS.md + opencode.json with flat command arrays)."""
    mcp_entries = _build_mcp_entries(manifest)
    rules_content = _build_rules_markdown(manifest)

    opencode_mcp: dict = {}
    for k, v in mcp_entries.items():
        flat_cmd = [v["command"], *v.get("args", [])]
        entry: dict = {"type": "local", "command": flat_cmd}
        if v.get("env"):
            entry["env"] = v["env"]
        opencode_mcp[k] = entry

    files = [
        AgentFile(
            path="AGENTS.md",
            content=rules_content,
            format="markdown",
        ),
    ]

    if opencode_mcp:
        files.append(
            AgentFile(
                path="opencode.json",
                content={"mcp": opencode_mcp},
                format="json",
            ),
        )

    return IdeAgentConfig(
        ide="opencode",
        files=files,
        mcp_servers=mcp_entries,
    )


_IDE_GENERATORS = {
    "claude-code": _generate_claude_code,
    "claude_code": _generate_claude_code,
    "cursor": _generate_cursor,
    "vscode": _generate_vscode,
    "gemini-cli": _generate_gemini_cli,
    "gemini_cli": _generate_gemini_cli,
    "kiro": _generate_kiro,
    "codex": _generate_codex,
    "copilot": _generate_copilot,
    "opencode": _generate_opencode,
}

SUPPORTED_IDES = [ide for ide in get_valid_ides() if ide in _IDE_GENERATORS or ide.replace("-", "_") in _IDE_GENERATORS]


def generate_ide_agent_files(
    manifest: AgentManifest,
    ide: str,
    observal_url: str = "",
    platform: str = "",
) -> IdeAgentConfig:
    """Generate IDE-specific agent files from a portable agent manifest.

    This is the universal entry point — takes a Pydantic AgentManifest
    and produces the correct file layout for any supported IDE.
    """
    generator = _IDE_GENERATORS.get(ide)
    if generator is None:
        raise ValueError(f"Unsupported IDE: {ide!r}. Supported: {', '.join(SUPPORTED_IDES)}")
    if observal_url:
        manifest._otlp_http_url = observal_url  # type: ignore[attr-defined]
        manifest._observal_url = observal_url  # type: ignore[attr-defined]
    if platform:
        manifest._platform = platform  # type: ignore[attr-defined]
    return generator(manifest)
