<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Adding a New IDE to Observal

This guide covers everything needed to add full IDE support. Observal manages
four component types per IDE: **MCP servers**, **skills**, **hooks**, and
**sandboxes**. Each IDE needs scanning (discovery), config generation (install),
hook instrumentation (telemetry), and session parsing (reconciliation).

## Overview: What "Supporting an IDE" Means

When a user runs `observal pull <agent>`, Observal writes IDE-specific files:

| Component | What gets written | Example |
|-----------|------------------|---------|
| MCP servers | JSON/TOML config with shim wrapping | `.cursor/mcp.json` |
| Skills | Markdown skill files in IDE's skill directory | `.claude/skills/my-skill/SKILL.md` |
| Hooks | Telemetry hook config that fires on tool use, session start/stop | `settings.json` hooks section |
| Sandboxes | MCP entry pointing to `observal-sandbox-run` | Added to MCP config |

When a user runs `observal scan`, Observal reads those same locations to discover what's installed.

## File Checklist

| # | File | What it does |
|---|------|-------------|
| 1 | `observal-server/schemas/ide_registry.py` | IDE metadata: paths, keys, event maps, formats |
| 2 | `observal_cli/ide_registry.py` | CLI mirror (must be identical, enforced by test) |
| 3 | `observal_cli/ide/<ide_name>.py` | CLI adapter: scanning, hook detection, shim status, managed file attribution |
| 4 | `observal_cli/ide/load_all.py` | Add import line for auto-registration |
| 5 | `observal_cli/ide/__init__.py` | Adapter registry and protocol validation |
| 6 | `observal-server/services/ide/<ide_name>.py` | Server adapter: config generation for install |
| 7 | `observal-server/services/ide/load_all.py` | Add import line for server adapter |
| 8 | `observal_cli/ide_specs/<ide_name>_hooks_spec.py` | Hook spec: what hooks to install, event names |
| 9 | `observal_cli/sessions/<ide_name>.py` | Session parser (if IDE writes JSONL sessions) |
| 10 | `observal_cli/hooks/<ide_name>_session_push.py` | Session push hook script |
| 11 | `observal_cli/cmd_doctor.py` | Doctor diagnose/patch/cleanup coverage for the new IDE |
| 12 | `observal_cli/layer.py` | Layer scanning globs (`IDE_LAYER_CONFIGS`) and active IDE detection |
| 13 | `tests/test_cli_ide_adapters.py` | Adapter unit tests |
| 14 | `/api/v1/config/ides` consumers | Frontend uses server IDE metadata through `useIdes()` |

## Step 1: Research the IDE

Before writing code, document these for the target IDE:

**MCP configuration:**
- Where does the IDE look for MCP server config? (path, format: JSON/TOML/YAML)
- What's the top-level key? (`mcpServers`, `servers`, `mcp`, etc.)
- Does it support stdio, SSE, or both transports?
- Home-level config path vs project-level config path?

**Skills:**
- Does the IDE have a skill/rules/instruction file concept?
- What format? (Markdown with YAML frontmatter, plain markdown, MDC, JSON)
- Where do skill files live? (project path, user/global path)

**Hooks:**
- Does the IDE fire lifecycle events? (tool use, session start/stop, errors)
- How are hooks registered? (JSON config, settings file, plugin system)
- What events are available? Map them to Observal's canonical events:
  - `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, `UserPromptSubmit`, `SubagentStop`
- Does the IDE support command hooks, HTTP hooks, or plugin hooks?

**Sessions:**
- Does the IDE write session logs? (JSONL, SQLite, custom format)
- Where are session files stored?
- What's the schema? (messages, tool calls, thinking blocks)

**Sandboxes:**
- Sandboxes are delivered as MCP servers, so if MCP works, sandboxes work.

## Step 2: Add IDE Registry Entry

Add to both `observal-server/schemas/ide_registry.py` and `observal_cli/ide_registry.py`.
The test `tests/test_constants_sync.py` enforces they're identical.

```python
"my-ide": {
    "display_name": "My IDE",
    "features": {"hooks", "mcp_servers", "skills"},
    "session_parser": "my_ide",       # or None
    "scopes": ["project", "user"],
    "default_scope": "project",
    "scope_labels": ("project (.my-ide/)", "user (~/.my-ide/)"),

    # MCP config
    "mcp_config_path": {
        "project": ".my-ide/mcp.json",
        "user": "~/.my-ide/mcp.json",
    },
    "mcp_servers_key": "mcpServers",
    "home_mcp_config": "~/.my-ide/mcp.json",

    # Skills
    "skill_file": {
        "project": ".my-ide/skills/{name}/SKILL.md",
        "user": "~/.my-ide/skills/{name}/SKILL.md",
    },
    "skill_format": "yaml_frontmatter",

    # Rules/Agent files
    "rules_file": {
        "project": ".my-ide/agents/{name}.md",
        "user": "~/.my-ide/agents/{name}.md",
    },
    "rules_format": "yaml_frontmatter",

    # Hooks
    "hook_type": "command",           # "command", "http", or "plugin"
    "hook_config_path": {
        "project": ".my-ide/settings.json",
        "user": "~/.my-ide/settings.json",
    },
    "hook_scripts_dir": ".my-ide/hooks",
    "hook_events_map": {
        "PreToolUse": "preToolUse",
        "PostToolUse": "postToolUse",
        "Stop": "sessionEnd",
        "SessionStart": "sessionStart",
        "UserPromptSubmit": "beforeSubmitPrompt",
    },

    "config_dir": ".my-ide",
    "accepts_model_choice": True,
    "auto_sentinel": None,
}
```

## Step 2.5: Update Doctor and Layer Scan (required)

Before moving on, always wire the new IDE into these shared paths:

- `observal_cli/cmd_doctor.py`:
  - Add a `_check_<ide>()` diagnose function
  - Add `_patch_<ide>()` support in `doctor patch`
  - Add `_cleanup_<ide>()` support in `doctor cleanup`
- `observal_cli/layer.py`:
  - Add user/project file globs under `IDE_LAYER_CONFIGS`
  - Ensure `_detect_active_ides()` has a reliable home-dir marker
- `observal_cli/ide/<ide_name>.py`:
  - Add `managed_agent_files`, `managed_skill_files`, and `managed_mcp_files` patterns for layer source attribution
  - Override `get_observal_managed_files()` only if simple `{name}` patterns are not enough

If these are skipped, the IDE can appear supported in pull/scan while doctor and layer observability remain incomplete.

## Step 3: Create CLI Adapter (Scanning)

Create `observal_cli/ide/my_ide.py`. This handles local discovery:

```python
# SPDX-FileCopyrightText: 2026 Your Name <your@email.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""My IDE adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from observal_cli.ide import (
    DiscoveredAgent,
    DiscoveredHook,
    DiscoveredMcp,
    DiscoveredSkill,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.ide.base import BaseAdapter
from observal_cli.shared.utils import (
    _OBSERVAL_HOOK_MARKERS,
    extract_mcp_servers,
    first_content_line,
    parse_frontmatter_field,
)


class MyIdeAdapter(BaseAdapter):
    managed_agent_files = ("user:agents/{name}.md", "project:.my-ide/agents/{name}.md")
    managed_skill_files = ("user:skills/{name}/SKILL.md", "project:.my-ide/skills/{name}/SKILL.md")
    managed_mcp_files = ("user:mcp.json", "project:.my-ide/mcp.json")

    @property
    def ide_name(self) -> str:
        return "my-ide"

    # ── Scanning ──────────────────────────────────────────────

    def scan_home(self, home: Path | None = None) -> ScanResult:
        """Discover MCPs, skills, hooks, agents from ~/.my-ide/"""
        home = home or Path.home()
        ide_dir = home / ".my-ide"
        if not ide_dir.exists():
            return ScanResult()

        mcps = self._scan_mcps(ide_dir / "mcp.json", "my-ide:global")
        skills = self._scan_skills(ide_dir / "skills")
        hooks = self._scan_hooks(ide_dir / "settings.json")
        agents = self._scan_agents(ide_dir / "agents")

        return ScanResult(mcps=mcps, skills=skills, hooks=hooks, agents=agents)

    def scan_project(self, project_dir: Path) -> ScanResult:
        """Discover MCPs, skills from .my-ide/ in a project."""
        ide_dir = project_dir / ".my-ide"
        if not ide_dir.exists():
            return ScanResult()

        mcps = self._scan_mcps(ide_dir / "mcp.json", "my-ide:project")
        skills = self._scan_skills(ide_dir / "skills")
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
        from observal_cli.ide_specs.my_ide_hooks_spec import build_hooks
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
                    description=f"My IDE MCP: {name}",
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
                    source="my-ide:skills",
                )
            )
        return skills

    def _scan_hooks(self, settings_file: Path) -> list[DiscoveredHook]:
        """Discover installed hooks from settings."""
        # Implement based on IDE's hook format
        return []

    def _scan_agents(self, agents_dir: Path) -> list[DiscoveredAgent]:
        """Discover agent definitions."""
        # Implement based on IDE's agent file format
        return []


register_adapter(MyIdeAdapter())
```

## Step 4: Create Server-Side Config Generator (Install)

Create `observal-server/services/ide/my_ide.py`. This generates files when
users run `observal pull` or install an agent:

```python
# SPDX-FileCopyrightText: 2026 Your Name <your@email.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""My IDE server-side config generator."""

from __future__ import annotations

from services.ide import ConfigContext, register_adapter


class MyIdeServerAdapter:
    @property
    def ide_name(self) -> str:
        return "my-ide"

    def generate_config(self, ctx: ConfigContext) -> dict:
        """Generate MCP config dict for this IDE."""
        return {"mcpServers": ctx.mcp_configs}

    def generate_files(self, ctx: ConfigContext) -> list[dict]:
        """Generate agent files (rules, skills, hooks) for this IDE."""
        files = []

        # Agent rules file
        if ctx.rules_content:
            files.append({
                "path": f".my-ide/agents/{ctx.safe_name}.md",
                "content": ctx.rules_content,
                "format": "markdown",
            })

        # Skill files
        from services.config.skill_builder import generate_skill_file
        for skill in ctx.skill_configs:
            entry = generate_skill_file(skill, "my-ide")
            if entry:
                files.append(entry)

        return files


register_adapter(MyIdeServerAdapter())
```

## Step 5: Create Hook Spec

Create `observal_cli/ide_specs/my_ide_hooks_spec.py`. This defines what
hooks `observal doctor patch --hook` installs:

```python
# SPDX-FileCopyrightText: 2026 Your Name <your@email.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Hook specification for My IDE."""


def build_hooks() -> dict:
    """Return the hooks config to merge into the IDE's settings.

    This is called by doctor patch and by the adapter's generate_hook_config().
    The format must match what the IDE expects in its hook config file.
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

Every IDE needs a session parser. Without one, `observal reconcile` cannot
push conversation context (assistant messages, tool results, thinking blocks)
to the server, making rich trace logs impossible. You only get bare hook
metadata without this.

**CLI side:** `observal_cli/sessions/my_ide.py` (reads local session files,
normalizes into records for upload)

**Server side:** `observal-server/services/session_parsers/my_ide.py` (reads
raw ClickHouse rows, normalizes into frontend-displayable events)

Both must produce the same normalized format so the trace viewer shows
consistent data regardless of whether it came from reconcile or live hooks.

See `sessions/claude_code.py` and `sessions/kiro.py` for reference
implementations. Key things to handle:

- User prompts and assistant responses
- Tool call requests and results
- Thinking/reasoning blocks (if the IDE exposes them)
- Error events
- Session boundaries (start/end markers)

Register the parser in `observal-server/services/session_parsers/__init__.py`:

```python
from .my_ide import parse_rows as _parse_my_ide

_PARSERS: dict[str, Callable] = {
    ...
    "my_ide": _parse_my_ide,
}
```

The `session_parser` key in the IDE registry entry must match this ID.

## Step 7: Create Session Push Hook

Create `observal_cli/hooks/my_ide_session_push.py` if the IDE needs a
custom session push script (most can reuse `session_push.py`).

## Step 8: Register Everything

1. `observal_cli/ide/load_all.py`:
   ```python
   from observal_cli.ide import my_ide as _my_ide  # noqa: F401
   ```

2. `observal_cli/ide/<ide_name>.py`: set managed file attribution patterns used by layer snapshots.

3. `observal-server/services/ide/load_all.py`:
   ```python
   from services.ide import my_ide as _my_ide  # noqa: F401
   ```

4. `observal_cli/cmd_scan.py`: add to `_IDE_HOME_DIRS`:
   ```python
   "my-ide": "~/.my-ide",
   ```

## Step 9: Tests

Minimum test coverage required:

```python
class TestMyIdeAdapter:
    def test_scan_home_empty(self, tmp_path):
        adapter = MyIdeAdapter()
        result = adapter.scan_home(tmp_path)
        assert result.mcps == []
        assert result.skills == []

    def test_scan_home_discovers_mcps(self, tmp_path):
        ide_dir = tmp_path / ".my-ide"
        ide_dir.mkdir()
        (ide_dir / "mcp.json").write_text('{"mcpServers": {"srv": {"command": "npx"}}}')
        adapter = MyIdeAdapter()
        result = adapter.scan_home(tmp_path)
        assert len(result.mcps) == 1
        assert result.mcps[0].name == "srv"

    def test_scan_home_discovers_skills(self, tmp_path):
        skill_dir = tmp_path / ".my-ide" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\ndescription: Does stuff\n---\n")
        adapter = MyIdeAdapter()
        result = adapter.scan_home(tmp_path)
        assert len(result.skills) == 1

    def test_scan_project_discovers_mcps(self, tmp_path):
        (tmp_path / ".my-ide").mkdir()
        (tmp_path / ".my-ide" / "mcp.json").write_text('{"mcpServers": {"p": {"command": "node"}}}')
        adapter = MyIdeAdapter()
        result = adapter.scan_project(tmp_path)
        assert len(result.mcps) == 1

    def test_detect_hooks_missing(self, tmp_path):
        adapter = MyIdeAdapter()
        assert adapter.detect_hooks(tmp_path) == "missing"

    def test_detect_hooks_installed(self, tmp_path):
        (tmp_path / "settings.json").write_text(json.dumps({
            "hooks": {
                "preToolUse": [{"command": "python -m observal_cli.hooks.session_push"}],
                "postToolUse": [{"command": "python -m observal_cli.hooks.session_push"}],
                "sessionEnd": [{"command": "python -m observal_cli.hooks.session_push"}],
            }
        }))
        adapter = MyIdeAdapter()
        assert adapter.detect_hooks(tmp_path) == "installed"

    def test_managed_files_for_layer_source_attribution(self):
        lockfile = {
            "ides": {
                "my-ide": {
                    "agents": [{"name": "agent-one", "components": [{"type": "skill", "name": "helper"}]}],
                }
            }
        }
        adapter = MyIdeAdapter()
        assert adapter.get_observal_managed_files(lockfile) == {
            "user:agents/agent-one.md",
            "project:.my-ide/agents/agent-one.md",
            "user:skills/helper/SKILL.md",
            "project:.my-ide/skills/helper/SKILL.md",
        }
```

## Step 10: Verify

```bash
# Constants in sync
cd observal-server && uv run pytest ../tests/test_constants_sync.py -q

# Adapter registration works
cd observal-server && uv run pytest ../tests/test_cli_ide_adapters.py -q

# Scan discovers your IDE
observal scan --ide my-ide

# Config generation works
cd observal-server && uv run pytest ../tests/test_agent_config_generator.py -q

# Install produces correct files
observal pull <some-agent> --ide my-ide --dry-run

# Hooks install correctly
observal doctor patch --hook --ide my-ide --dry-run
```

## Architecture Notes

**Skills are mostly universal.** All IDEs that support skills use the same
pattern: a `SKILL.md` file with YAML frontmatter (or plain markdown) placed
in the IDE's skill directory. The only things that vary are the directory path
(defined in `skill_file` in the registry) and the frontmatter format (defined
in `skill_format`). No IDE-specific skill generation code is needed beyond
setting those two registry fields correctly. The shared `generate_skill_file()`
in `services/config/skill_builder.py` handles all IDEs.

**Sandboxes are just MCP servers.** They use `observal-sandbox-run` as the
command. If MCP install works for your IDE, sandboxes work automatically.
No additional sandbox-specific code is needed per IDE.

Other notes:

- Adapters are self-contained: one file handles scanning, hook detection, and shim status
- Shared utilities in `observal_cli/shared/utils.py`: `extract_mcp_servers`, `parse_frontmatter_field`, `is_already_shimmed`, `_OBSERVAL_HOOK_MARKERS`
- `BaseAdapter` in `observal_cli/ide/base.py` provides feature-gating via `_check_feature()`
- `ensure_loaded()` guarantees all adapters are registered before cross-adapter operations
- MCP deduplication in scan uses first-discovered-wins
- The shim (`observal-shim`) is transport-agnostic: it wraps any stdio MCP server regardless of IDE
- Sandboxes are just MCP servers backed by `observal-sandbox-run`, so if MCP install works, sandboxes work automatically
- Skills use the IDE's native skill/rule file format, resolved from `skill_file` and `skill_format` in the registry
