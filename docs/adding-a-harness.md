<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Adding a New Harness to Observal

This guide covers everything needed to add full harness support. Observal manages
four component types per harness: **MCP servers**, **skills**, **hooks**, and
**sandboxes**. Each harness needs scanning (discovery), config generation (install),
hook instrumentation (telemetry), and session parsing (reconciliation).

## Overview: What "Supporting a harness" Means

When a user runs `observal pull <agent>`, Observal writes harness-specific files:

| Component | What gets written | Example |
|-----------|------------------|---------|
| MCP servers | JSON/TOML config with shim wrapping | `.cursor/mcp.json` |
| Skills | Markdown skill files in harness's skill directory | `.claude/skills/my-skill/SKILL.md` |
| Hooks | Telemetry hook config that fires on tool use, session start/stop | `settings.json` hooks section |
| Sandboxes | MCP entry pointing to `observal-sandbox-run` | Added to MCP config |

When a user runs `observal scan`, Observal reads those same locations to discover what's installed.

## File Checklist

| # | File | What it does |
|---|------|-------------|
| 1 | `observal-server/schemas/harness_registry.py` | harness metadata: paths, keys, event maps, formats |
| 2 | `observal_cli/harness_registry.py` | CLI mirror (must be identical, enforced by test) |
| 3 | `observal_cli/harness/<harness_name>.py` | CLI adapter: scanning, hook detection, shim status, managed file attribution |
| 4 | `observal_cli/harness/load_all.py` | Add import line for auto-registration |
| 5 | `observal_cli/harness/__init__.py` | Adapter registry and protocol validation |
| 6 | `observal-server/services/harness/<harness_name>.py` | Server adapter: config generation for install |
| 7 | `observal-server/services/harness/load_all.py` | Add import line for server adapter |
| 8 | `observal_cli/harness_specs/<harness_name>_hooks_spec.py` | Hook spec: what hooks to install, event names |
| 9 | `observal_cli/sessions/<harness_name>.py` | Session parser (if harness writes JSONL sessions) |
| 10 | `observal_cli/hooks/<harness_name>_session_push.py` | Session push hook script |
| 11 | `observal_cli/cmd_doctor.py` | Doctor diagnose/patch/cleanup coverage for the new harness |
| 12 | `observal_cli/layer.py` | Layer scanning globs (`HARNESS_LAYER_CONFIGS`) and active harness detection |
| 13 | `tests/test_cli_ide_adapters.py` | Adapter unit tests |
| 14 | `/api/v1/config/harnesses` consumers | Frontend uses server harness metadata through `useHarnesses()` |

## Step 1: Research the harness

Before writing code, document these for the target harness:

**MCP configuration:**
- Where does the harness look for MCP server config? (path, format: JSON/TOML/YAML)
- What's the top-level key? (`mcpServers`, `servers`, `mcp`, etc.)
- Does it support stdio, SSE, or both transports?
- Home-level config path vs project-level config path?

**Skills:**
- Does the harness have a skill/rules/instruction file concept?
- What format? (Markdown with YAML frontmatter, plain markdown, MDC, JSON)
- Where do skill files live? (project path, user/global path)

**Hooks:**
- Does the harness fire lifecycle events? (tool use, session start/stop, errors)
- How are hooks registered? (JSON config, settings file, plugin system)
- What events are available? Map them to Observal's canonical events:
  - `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, `UserPromptSubmit`, `SubagentStop`
- Does the harness support command hooks, HTTP hooks, or plugin hooks?

**Sessions:**
- Does the harness write session logs? (JSONL, SQLite, custom format)
- Where are session files stored?
- What's the schema? (messages, tool calls, thinking blocks)

**Sandboxes:**
- Sandboxes are delivered as MCP servers, so if MCP works, sandboxes work.

## Step 2: Add Harness Registry Entry

Add to both `observal-server/schemas/harness_registry.py` and `observal_cli/harness_registry.py`.
The test `tests/test_constants_sync.py` enforces they're identical.

```python
"my-harness": {
    "display_name": "My harness",
    "capabilities": {"hooks", "mcp_servers", "skills"},
    "session_parser": "my_harness",       # or None
    "scopes": ["project", "user"],
    "default_scope": "project",
    "scope_labels": ("project (.my-harness/)", "user (~/.my-harness/)"),

    # MCP config
    "mcp_config": {
        "project": ".my-harness/mcp.json",
        "user": "~/.my-harness/mcp.json",
    },
    "mcp_servers_key": "mcpServers",
    "home_mcp_config": "~/.my-harness/mcp.json",

    # Skills
    "skills": {
        "project": ".my-harness/skills/{name}/SKILL.md",
        "user": "~/.my-harness/skills/{name}/SKILL.md",
    },
    "skill_format": "yaml_frontmatter",

    # Rules/Agent files
    "agent_profile": {
        "project": ".my-harness/agents/{name}.md",
        "user": "~/.my-harness/agents/{name}.md",
    },
    "agent_profile_format": "yaml_frontmatter",

    # Hooks
    "hook_type": "command",           # "command", "http", or "plugin"
    "hooks": {
        "project": ".my-harness/settings.json",
        "user": "~/.my-harness/settings.json",
    },
    "hook_scripts_dir": ".my-harness/hooks",
    "hook_events_map": {
        "PreToolUse": "preToolUse",
        "PostToolUse": "postToolUse",
        "Stop": "sessionEnd",
        "SessionStart": "sessionStart",
        "UserPromptSubmit": "beforeSubmitPrompt",
    },

    "config_dir": ".my-harness",
}
```

## Step 2.5: Update Doctor and Layer Scan (required)

Before moving on, always wire the new harness into these shared paths:

- `observal_cli/cmd_doctor.py`:
  - Add a `_check_<harness>()` diagnose function
  - Add `_patch_<harness>()` support in `doctor patch`
  - Add `_cleanup_<harness>()` support in `doctor cleanup`
- `observal_cli/layer.py`:
  - Add user/project file globs under `HARNESS_LAYER_CONFIGS`
- `observal_cli/harness/<harness_name>.py`:
  - Add `home_markers` for active harness detection when the harness has a reliable home config marker. Glob patterns are supported.
  - Add `managed_agent_profiles`, `managed_skills`, and `managed_mcp_files` patterns for layer source attribution
  - Override `get_observal_managed_files()` only if simple `{name}` patterns are not enough

If these are skipped, the harness can appear supported in pull/scan while doctor and layer observability remain incomplete.

## Step 3: Create CLI Adapter (Scanning)

Create `observal_cli/harness/my_harness.py`. This handles local discovery:

```python
# SPDX-FileCopyrightText: 2026 Your Name <your@email.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""My harness adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from observal_cli.harness import (
    DiscoveredAgent,
    DiscoveredHook,
    DiscoveredMcp,
    DiscoveredSkill,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.harness.base import BaseAdapter
from observal_cli.shared.utils import (
    _OBSERVAL_HOOK_MARKERS,
    extract_mcp_servers,
    first_content_line,
    parse_frontmatter_field,
)


class MyHarnessAdapter(BaseAdapter):
    home_markers = (".my-harness",)
    managed_agent_profiles = ("user:agents/{name}.md", "project:.my-harness/agents/{name}.md")
    managed_skills = ("user:skills/{name}/SKILL.md", "project:.my-harness/skills/{name}/SKILL.md")
    managed_mcp_files = ("user:mcp.json", "project:.my-harness/mcp.json")

    @property
    def harness_name(self) -> str:
        return "my-harness"

    # ── Scanning ──────────────────────────────────────────────

    def scan_home(self, home: Path | None = None) -> ScanResult:
        """Discover MCPs, skills, hooks, agents from ~/.my-harness/"""
        home = home or Path.home()
        harness_dir = home / ".my-harness"
        if not harness_dir.exists():
            return ScanResult()

        mcps = self._scan_mcps(harness_dir / "mcp.json", "my-harness:global")
        skills = self._scan_skills(harness_dir / "skills")
        hooks = self._scan_hooks(harness_dir / "settings.json")
        agents = self._scan_agents(harness_dir / "agents")

        return ScanResult(mcps=mcps, skills=skills, hooks=hooks, agents=agents)

    def scan_project(self, project_dir: Path) -> ScanResult:
        """Discover MCPs, skills from .my-harness/ in a project."""
        harness_dir = project_dir / ".my-harness"
        if not harness_dir.exists():
            return ScanResult()

        mcps = self._scan_mcps(harness_dir / "mcp.json", "my-harness:project")
        skills = self._scan_skills(harness_dir / "skills")
        return ScanResult(mcps=mcps, skills=skills)

    # ── Hook detection ────────────────────────────────────────

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=["PreToolUse", "PostToolUse", "Stop", "SessionStart"],
            format="command",
            markers=["observal", "OBSERVAL"],
        )

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate the hooks config dict to write into settings."""
        # Import from your hook spec module
        from observal_cli.harness_specs.my_harness_hooks_spec import build_hooks
        return build_hooks()

    def detect_hooks(self, config_dir: Path) -> str:
        """Check if Observal hooks are installed. Return 'installed'|'partial'|'missing'."""
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
        for _evt, entries in hooks.items():
            if isinstance(entries, list):
                for h in entries:
                    if isinstance(h, dict) and any(
                        m in h.get("command", "") for m in _OBSERVAL_HOOK_MARKERS
                    ):
                        found += 1
                        break
        return "installed" if found >= 3 else ("partial" if found > 0 else "missing")

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)

    # ── Private helpers ───────────────────────────────────────

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
                    description=f"My harness MCP: {name}",
                    source=source,
                )
                for name, cfg in servers.items()
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
                    source="my-harness:skills",
                )
            )
        return skills

    def _scan_hooks(self, settings_file: Path) -> list[DiscoveredHook]:
        """Discover installed hooks from settings."""
        # Implement based on harness's hook format
        return []

    def _scan_agents(self, agents_dir: Path) -> list[DiscoveredAgent]:
        """Discover agent definitions."""
        # Implement based on harness's agent file format
        return []


register_adapter(MyHarnessAdapter())
```

## Step 4: Create Server-Side Config Generator (Install)

Create `observal-server/services/harness/my_harness.py`. This generates files when
users run `observal pull` or install an agent:

```python
# SPDX-FileCopyrightText: 2026 Your Name <your@email.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""My harness server-side config generator."""

from __future__ import annotations

from services.harness import ConfigContext, register_adapter


class MyIdeServerAdapter:
    @property
    def harness_name(self) -> str:
        return "my-harness"

    def generate_config(self, ctx: ConfigContext) -> dict:
        """Generate MCP config dict for this harness."""
        return {"mcpServers": ctx.mcp_configs}

    def generate_files(self, ctx: ConfigContext) -> list[dict]:
        """Generate agent files (rules, skills, hooks) for this harness."""
        files = []

        # Agent rules file
        if ctx.rules_content:
            files.append({
                "path": f".my-harness/agents/{ctx.safe_name}.md",
                "content": ctx.rules_content,
                "format": "markdown",
            })

        # Skill files
        from services.config.skill_builder import generate_skill
        for skill in ctx.skill_configs:
            entry = generate_skill(skill, "my-harness")
            if entry:
                files.append(entry)

        return files


register_adapter(MyIdeServerAdapter())
```

## Step 5: Create Hook Spec

Create `observal_cli/harness_specs/my_harness_hooks_spec.py`. This defines what
hooks `observal doctor patch --hook` installs:

```python
# SPDX-FileCopyrightText: 2026 Your Name <your@email.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Hook specification for My harness."""


def build_hooks() -> dict:
    """Return the hooks config to merge into the harness's settings.

    This is called by doctor patch and by the adapter's generate_hook_config().
    The format must match what the harness expects in its hook config file.
    """
    return {
        "hooks": {
            "preToolUse": [
                {
                    "type": "command",
                    "command": "python -m observal_cli.hooks.session_push pre_tool_use",
                }
            ],
            "postToolUse": [
                {
                    "type": "command",
                    "command": "python -m observal_cli.hooks.session_push post_tool_use",
                }
            ],
            "sessionEnd": [
                {
                    "type": "command",
                    "command": "python -m observal_cli.hooks.session_push stop",
                }
            ],
        }
    }
```

## Step 6: Create Session Parser (required)

Every harness needs a session parser. Without one, `observal reconcile` cannot
push conversation context (assistant messages, tool results, thinking blocks)
to the server, making rich trace logs impossible. You only get bare hook
metadata without this.

**CLI side:** `observal_cli/sessions/my_harness.py` (reads local session files,
normalizes into records for upload)

**Server side:** `observal-server/services/session_parsers/my_harness.py` (reads
raw ClickHouse rows, normalizes into frontend-displayable events)

Both must produce the same normalized format so the trace viewer shows
consistent data regardless of whether it came from reconcile or live hooks.

See `sessions/claude_code.py` and `sessions/kiro.py` for reference
implementations. Key things to handle:

- User prompts and assistant responses
- Tool call requests and results
- Thinking/reasoning blocks (if the harness exposes them)
- Error events
- Session boundaries (start/end markers)

Register the parser in `observal-server/services/session_parsers/__init__.py`:

```python
from .my_harness import parse_rows as _parse_my_harness

_PARSERS: dict[str, Callable] = {
    ...
    "my_harness": _parse_my_harness,
}
```

The `session_parser` key in the harness registry entry must match this ID.

## Step 7: Create Session Push Hook

Create `observal_cli/hooks/my_harness_session_push.py` if the harness needs a
custom session push script (most can reuse `session_push.py`).

## Step 8: Register Everything

1. `observal_cli/harness/load_all.py`:
   ```python
   from observal_cli.harness import my_harness as _my_harness  # noqa: F401
   ```

2. `observal_cli/harness/<harness_name>.py`: set `home_markers` and managed file attribution patterns used by layer snapshots.

3. `observal-server/services/harness/load_all.py`:
   ```python
   from services.harness import my_harness as _my_harness  # noqa: F401
   ```

4. `observal_cli/cmd_scan.py`: add to `_HARNESS_HOME_DIRS`:
   ```python
   "my-harness": "~/.my-harness",
   ```

## Step 9: Tests

Minimum test coverage required:

```python
class TestMyHarnessAdapter:
    def test_scan_home_empty(self, tmp_path):
        adapter = MyHarnessAdapter()
        result = adapter.scan_home(tmp_path)
        assert result.mcps == []
        assert result.skills == []

    def test_is_installed_uses_home_marker(self, tmp_path):
        adapter = MyHarnessAdapter()
        assert adapter.is_installed(tmp_path) is False
        (tmp_path / ".my-harness").mkdir()
        assert adapter.is_installed(tmp_path) is True

    def test_scan_home_discovers_mcps(self, tmp_path):
        harness_dir = tmp_path / ".my-harness"
        harness_dir.mkdir()
        (harness_dir / "mcp.json").write_text('{"mcpServers": {"srv": {"command": "npx"}}}')
        adapter = MyHarnessAdapter()
        result = adapter.scan_home(tmp_path)
        assert len(result.mcps) == 1
        assert result.mcps[0].name == "srv"

    def test_scan_home_discovers_skills(self, tmp_path):
        skill_dir = tmp_path / ".my-harness" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\ndescription: Does stuff\n---\n")
        adapter = MyHarnessAdapter()
        result = adapter.scan_home(tmp_path)
        assert len(result.skills) == 1

    def test_scan_project_discovers_mcps(self, tmp_path):
        (tmp_path / ".my-harness").mkdir()
        (tmp_path / ".my-harness" / "mcp.json").write_text('{"mcpServers": {"p": {"command": "node"}}}')
        adapter = MyHarnessAdapter()
        result = adapter.scan_project(tmp_path)
        assert len(result.mcps) == 1

    def test_detect_hooks_missing(self, tmp_path):
        adapter = MyHarnessAdapter()
        assert adapter.detect_hooks(tmp_path) == "missing"

    def test_detect_hooks_installed(self, tmp_path):
        (tmp_path / "settings.json").write_text(json.dumps({
            "hooks": {
                "preToolUse": [{"command": "python -m observal_cli.hooks.session_push"}],
                "postToolUse": [{"command": "python -m observal_cli.hooks.session_push"}],
                "sessionEnd": [{"command": "python -m observal_cli.hooks.session_push"}],
            }
        }))
        adapter = MyHarnessAdapter()
        assert adapter.detect_hooks(tmp_path) == "installed"

    def test_managed_files_for_layer_source_attribution(self):
        lockfile = {
            "harnesses": {
                "my-harness": {
                    "agents": [{"name": "agent-one", "components": [{"type": "skill", "name": "helper"}]}],
                }
            }
        }
        adapter = MyHarnessAdapter()
        assert adapter.get_observal_managed_files(lockfile) == {
            "user:agents/agent-one.md",
            "project:.my-harness/agents/agent-one.md",
            "user:skills/helper/SKILL.md",
            "project:.my-harness/skills/helper/SKILL.md",
        }
```

## Step 10: Verify

```bash
# Constants in sync
cd observal-server && uv run pytest ../tests/test_constants_sync.py -q

# Adapter registration works
cd observal-server && uv run pytest ../tests/test_cli_ide_adapters.py -q

# Scan discovers your harness
observal scan --harness my-harness

# Config generation works
cd observal-server && uv run pytest ../tests/test_agent_config_generator.py -q

# Install produces correct files
observal pull <some-agent> --harness my-harness --dry-run

# Hooks install correctly
observal doctor patch --hook --harness my-harness --dry-run
```

## Architecture Notes

**Skills are mostly universal.** All harnesses that support skills use the same
pattern: a `SKILL.md` file with YAML frontmatter (or plain markdown) placed
in the harness's skill directory. The only things that vary are the directory path
(defined in `skill` in the registry) and the frontmatter format (defined
in `skill_format`). No harness-specific skill generation code is needed beyond
setting those two registry fields correctly. The shared `generate_skill()`
in `services/config/skill_builder.py` handles all harnesses.

**Sandboxes are just MCP servers.** They use `observal-sandbox-run` as the
command. If MCP install works for your harness, sandboxes work automatically.
No additional sandbox-specific code is needed per harness.

Other notes:

- Adapters are self-contained: one file handles scanning, hook detection, and shim status
- Shared utilities in `observal_cli/shared/utils.py`: `extract_mcp_servers`, `parse_frontmatter_field`, `is_already_shimmed`, `_OBSERVAL_HOOK_MARKERS`
- `BaseAdapter` in `observal_cli/harness/base.py` provides feature-gating via `_check_feature()`
- `ensure_loaded()` guarantees all adapters are registered before cross-adapter operations
- MCP deduplication in scan uses first-discovered-wins
- The shim (`observal-shim`) is transport-agnostic: it wraps any stdio MCP server regardless of harness
- Sandboxes are just MCP servers backed by `observal-sandbox-run`, so if MCP install works, sandboxes work automatically
- Skills use the harness's native skill/rule file format, resolved from `skill` and `skill_format` in the registry
