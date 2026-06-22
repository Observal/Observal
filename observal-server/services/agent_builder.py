# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Agent builder - composes resolved components into portable agent manifests.

Generates harness-specific agent files from a ResolvedAgent:
- Claude Code: .claude/agents/<name>.md (markdown) + MCP JSON config
- Cursor: .cursor/agents/<name>.md (subagent markdown) + .cursor/mcp.json
- Gemini CLI: GEMINI.md (markdown) + MCP JSON config
- Kiro: ~/.kiro/agents/<name>.json (JSON)
- Codex: ~/.codex/agents/<name>.toml (custom agent)
- GitHub Copilot: .github/copilot-instructions.md (markdown)
- OpenCode: .opencode/agents/<name>.md (markdown) + opencode.json (MCP config)

"""

import json

from loguru import logger as optic

from schemas.harness_registry import get_valid_harnesses
from services.agent_builder_types import (
    AgentFile,
    AgentManifest,
    CompositionSummary,
    HarnessAgentConfig,
    HookConfigEntry,
    HookInstallEntry,
    ManifestComponent,
    ManifestComponents,
    ManifestError,
)
from services.agent_resolver import ResolvedAgent, ResolvedComponent
from services.harness.helpers import _KIRO_EVENT_MAP, _wrap_kiro_prompt
from services.model_resolver import resolve_saved_value
from services.shared.utils import sanitize_name as _sanitize_name


def _saved_model_for(manifest: "AgentManifest", harness: str) -> str | None:
    """Compute the harness-formatted saved model from a manifest.

    Manifest builders are synchronous and do not consult the live catalog.
    They trust the saved per-harness override (or `model_name` for Claude Code's
    backward-compat path) and apply only ID translation. Catalog validation
    happens in the install path via ``resolve_model_for_harness``.
    """
    return resolve_saved_value(
        harness,
        model_name=manifest.model_name or "",
        models_by_harness=manifest.models_by_harness or {},
    )


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
        if comp.extra.get("skill_md_content"):
            kwargs["config_override"] = {"skill_md_content": comp.extra["skill_md_content"]}
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
    optic.trace("building agent config for {}", resolved.agent_name)
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
        models_by_harness=resolved.models_by_harness,
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
    optic.trace("building agent config for {}", resolved.agent_name)
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


# ── harness Agent File Generation ──────────────────────────────────────


def _build_mcp_entries(manifest: AgentManifest) -> dict:
    """Build MCP server config entries from manifest components."""
    from services.config.mcp_builder import build_mcp_entries

    return build_mcp_entries(manifest)


def _build_skills(manifest: AgentManifest, harness: str) -> list[AgentFile]:
    """Generate harness-specific skill files from manifest skills."""
    from services.config.skill_builder import build_skills

    return build_skills(manifest, harness)


def _build_rules_markdown(manifest: AgentManifest) -> str:
    """Build markdown rules content from the agent manifest."""
    sections = []

    if manifest.prompt:
        sections.append(manifest.prompt)

    # Component summary sections
    if manifest.components.mcps:
        lines = ["## MCP Servers", ""]
        for mcp in manifest.components.mcps:
            desc = f" - {mcp.description}" if mcp.description else ""
            lines.append(f"- **{mcp.name}** v{mcp.version}{desc}")
        sections.append("\n".join(lines))

    if manifest.components.skills:
        lines = ["## Skills", ""]
        for skill in manifest.components.skills:
            cmd = f" (`/{skill.slash_command}`)" if skill.slash_command else ""
            desc = f" - {skill.description}" if skill.description else ""
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


def _materialize_hook_components(
    manifest: AgentManifest, harness: str
) -> tuple[list[HookInstallEntry], list[HookConfigEntry]]:
    """Generate hook files + configs for all hook components in an agent manifest.

    Uses the harness registry to map events and determine script paths.
    Returns (hook_files, hook_configs) to be included in HarnessAgentConfig.
    """
    from schemas.harness_registry import HARNESS_REGISTRY

    if not manifest.components.hooks:
        return [], []

    ide_info = HARNESS_REGISTRY.get(harness, {})
    events_map = ide_info.get("hook_events_map", {})
    hook_scripts_dir = ide_info.get("hook_scripts_dir", "")
    hooks_dict = ide_info.get("hooks", {})
    hook_type = ide_info.get("hook_type")

    # Can't generate for plugin-based harnesses
    if hook_type == "plugin":
        return [], []

    config_path = hooks_dict.get("project") or hooks_dict.get("user") or ""

    hook_files: list[HookInstallEntry] = []
    all_hook_entries: dict[str, list] = {}  # ide_event -> list of hook entries

    for hook in manifest.components.hooks:
        if not hook.event or not hook.handler_config:
            continue

        ide_event = events_map.get(hook.event)
        if not ide_event:
            continue

        handler_type = hook.handler_type or "command"
        command = hook.handler_config.get("command", "")
        timeout = hook.handler_config.get("timeout")
        script_filename = getattr(hook, "script_filename", None) or (getattr(hook, "config_override", None) or {}).get(
            "script_filename"
        )
        script_content = getattr(hook, "script_content", None) or (getattr(hook, "config_override", None) or {}).get(
            "script_content"
        )

        # If hook has a script, write it and rewrite the command
        actual_command = command
        if script_content and script_filename and hook_scripts_dir:
            script_path = f"{hook_scripts_dir}/{script_filename}"
            hook_files.append(
                HookInstallEntry(
                    path=script_path,
                    content=script_content,
                    executable=True,
                )
            )
            actual_command = script_path

        # Build harness-specific hook entry
        if harness == "claude-code":
            hook_entry: dict = {"type": handler_type, "command": actual_command}
            if timeout:
                hook_entry["timeout"] = timeout
            all_hook_entries.setdefault(ide_event, []).append({"matcher": "*", "hooks": [hook_entry]})
        elif harness == "cursor":
            all_hook_entries.setdefault(ide_event, []).append({"command": actual_command})
        else:
            all_hook_entries.setdefault(ide_event, []).append({"command": actual_command})

    # Build the merged config snippet
    hook_configs: list[HookConfigEntry] = []
    if all_hook_entries and config_path:
        snippet = {"version": 1, "hooks": all_hook_entries} if harness == "cursor" else {"hooks": all_hook_entries}
        hook_configs.append(
            HookConfigEntry(
                config_path=config_path,
                config_snippet=snippet,
                merge=True,
            )
        )

    return hook_files, hook_configs


def _generate_claude_code(manifest: AgentManifest) -> HarnessAgentConfig:
    """Generate Claude Code agent config (.claude/agents/<name>.md + MCP commands)."""
    safe_name = _sanitize_name(manifest.name)
    mcp_entries = _build_mcp_entries(manifest)
    rules_content = _build_rules_markdown(manifest)

    setup_commands = []
    for name, cfg in mcp_entries.items():
        cmd = cfg.get("command", "observal-shim")
        args = cfg.get("args", [])
        setup_commands.append(["claude", "mcp", "add", name, "--", cmd, *args])

    desc_line = (manifest.description or safe_name).replace("\n", " ").strip()
    frontmatter_lines = [
        "---",
        f"name: {safe_name}",
        f'description: "{desc_line}"',
    ]
    saved_model = _saved_model_for(manifest, "claude-code")
    if saved_model:
        frontmatter_lines.append(f"model: {saved_model}")
    if mcp_entries:
        frontmatter_lines.append("mcpServers:")
        for mcp_name in mcp_entries:
            frontmatter_lines.append(f"  - {mcp_name}")
    frontmatter_lines.append("---")
    agent_content = "\n".join(frontmatter_lines) + "\n\n" + rules_content

    skills = _build_skills(manifest, "claude-code")

    env: dict[str, str] = {}

    return HarnessAgentConfig(
        harness="claude-code",
        files=[
            AgentFile(
                path=f".claude/agents/{safe_name}.md",
                content=agent_content,
                format="markdown",
            ),
            *skills,
        ],
        mcp_servers=mcp_entries,
        env=env,
        setup_commands=setup_commands,
    )


def _generate_cursor(manifest: AgentManifest) -> HarnessAgentConfig:
    """Generate Cursor subagent config (.cursor/agents/<name>.md + .cursor/mcp.json)."""
    safe_name = _sanitize_name(manifest.name)
    mcp_entries = _build_mcp_entries(manifest)
    rules_content = _build_rules_markdown(manifest)
    desc_line = (manifest.description or safe_name).replace("\n", " ").strip()[:200]
    model = manifest.model_name or "inherit"
    agent_content = f"---\nname: {safe_name}\ndescription: {desc_line!r}\nmodel: {model}\n---\n\n{rules_content}"

    skills = _build_skills(manifest, "cursor")

    return HarnessAgentConfig(
        harness="cursor",
        files=[
            AgentFile(
                path=f".cursor/agents/{safe_name}.md",
                content=agent_content,
                format="markdown",
            ),
            AgentFile(
                path=".cursor/mcp.json",
                content={"mcpServers": mcp_entries},
                format="json",
            ),
            *skills,
        ],
        mcp_servers=mcp_entries,
    )


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


def _generate_kiro(manifest: AgentManifest) -> HarnessAgentConfig:
    """Generate Kiro agent config."""
    safe_name = _sanitize_name(manifest.name)
    mcp_entries = _build_mcp_entries(manifest)
    observal_url = getattr(manifest, "_observal_url", "") or ""
    platform = getattr(manifest, "_platform", "") or ""
    hooks = _build_kiro_hooks(safe_name, observal_url, platform)
    _materialize_kiro_hook_components(hooks, manifest)
    saved_model = _saved_model_for(manifest, "kiro")
    content = {
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
            "skill://.kiro/skills/**/SKILL.md",
            "skill://~/.kiro/skills/**/SKILL.md",
        ],
        "hooks": hooks,
        "toolsSettings": {},
        "includeMcpJson": True,
        "model": saved_model,
    }
    skills = _build_skills(manifest, "kiro")

    return HarnessAgentConfig(
        harness="kiro",
        files=[
            AgentFile(
                path=f"~/.kiro/agents/{safe_name}.json",
                content=content,
                format="json",
            ),
            *skills,
        ],
        mcp_servers=mcp_entries,
    )


def _generate_codex(manifest: AgentManifest) -> HarnessAgentConfig:
    """Generate Codex custom agent config."""
    safe_name = _sanitize_name(manifest.name)
    rules_content = _build_rules_markdown(manifest)
    desc_line = (manifest.description or safe_name).replace("\n", " ").strip()[:200]
    saved_model = _saved_model_for(manifest, "codex")
    agent_lines = [
        f"name = {json.dumps(safe_name)}",
        f"description = {json.dumps(desc_line or safe_name)}",
        f"developer_instructions = {json.dumps(rules_content)}",
    ]
    if saved_model:
        agent_lines.append(f"model = {json.dumps(saved_model)}")

    files = [
        AgentFile(
            path=f".codex/agents/{safe_name}.toml",
            content="\n".join(agent_lines) + "\n",
            format="toml",
        ),
    ]

    skills = _build_skills(manifest, "codex")
    files.extend(skills)

    return HarnessAgentConfig(
        harness="codex",
        files=files,
    )


def _generate_copilot(manifest: AgentManifest) -> HarnessAgentConfig:
    """Generate GitHub Copilot custom agent config."""
    safe_name = _sanitize_name(manifest.name)
    mcp_entries = _build_mcp_entries(manifest)
    rules_content = _build_rules_markdown(manifest)
    desc_line = (manifest.description or safe_name).replace("\n", " ").strip()[:200]
    agent_content = (
        f"---\nname: {safe_name}\ndescription: \"{desc_line}\"\ntarget: vscode\ntools: ['*']\n---\n\n{rules_content}"
    )

    files = [
        AgentFile(
            path=f".github/agents/{safe_name}.agent.md",
            content=agent_content,
            format="markdown",
        ),
    ]

    skills = _build_skills(manifest, "copilot")
    files.extend(skills)

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

    return HarnessAgentConfig(
        harness="copilot",
        files=files,
        mcp_servers=mcp_entries,
    )


def _generate_opencode(manifest: AgentManifest) -> HarnessAgentConfig:
    """Generate OpenCode agent config (.opencode/agents/<name>.md + opencode.json with flat command arrays)."""
    safe_name = _sanitize_name(manifest.name)
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
            path=f".opencode/agents/{safe_name}.md",
            content=rules_content,
            format="markdown",
        ),
    ]

    saved_model = _saved_model_for(manifest, "opencode")
    if opencode_mcp or saved_model:
        opencode_content: dict = {}
        if opencode_mcp:
            opencode_content["mcp"] = opencode_mcp
        if saved_model:
            opencode_content["model"] = saved_model
        files.append(
            AgentFile(
                path="opencode.json",
                content=opencode_content,
                format="json",
            ),
        )

    return HarnessAgentConfig(
        harness="opencode",
        files=[*files, *_build_skills(manifest, "opencode")],
        mcp_servers=mcp_entries,
    )


_HARNESS_GENERATORS = {
    "claude-code": _generate_claude_code,
    "claude_code": _generate_claude_code,
    "cursor": _generate_cursor,
    "kiro": _generate_kiro,
    "codex": _generate_codex,
    "copilot": _generate_copilot,
    "opencode": _generate_opencode,
}

SUPPORTED_HARNESSES = [
    harness
    for harness in get_valid_harnesses()
    if harness in _HARNESS_GENERATORS or harness.replace("-", "_") in _HARNESS_GENERATORS
]


def generate_harness_agent_profiles(
    manifest: AgentManifest,
    harness: str,
    observal_url: str = "",
    platform: str = "",
) -> HarnessAgentConfig:
    """Generate harness-specific agent files from a portable agent manifest.

    This is the universal entry point - takes a Pydantic AgentManifest
    and produces the correct file layout for any supported harness.
    """
    optic.trace("generating {} config for agent {}", harness, manifest.name)
    generator = _HARNESS_GENERATORS.get(harness)
    if generator is None:
        raise ValueError(f"Unsupported harness: {harness!r}. Supported: {', '.join(SUPPORTED_HARNESSES)}")
    if observal_url:
        manifest._observal_url = observal_url  # type: ignore[attr-defined]
    if platform:
        manifest._platform = platform  # type: ignore[attr-defined]
    config = generator(manifest)

    # Materialize hook components for all harnesses (except Kiro which does it inline)
    if harness != "kiro" and manifest.components.hooks:
        hook_files, hook_configs = _materialize_hook_components(manifest, harness)
        config.hook_files = hook_files
        config.hook_configs = hook_configs

    return config
