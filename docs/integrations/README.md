# Integrations

Observal supports seven IDEs / AI coding tools. The depth of support varies — some have native OpenTelemetry export and integrate almost transparently; others need hook-based workarounds until their upstream catches up.

## Compatibility matrix

| IDE | Skills | Superpowers | Hook bridge | MCP servers | Rules | Steering files | OTLP telemetry |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| [Claude Code](claude-code.md) | ✅ | — | ✅ | ✅ | ✅ | — | ✅ |
| [Kiro CLI](kiro.md) | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Cursor](cursor.md) | — | — | — | ✅ | ✅ | — | — |
| [Gemini CLI](gemini-cli.md) | — | — | — | ✅ | ✅ | — | — |
| [VS Code](vscode.md) | — | — | — | ✅ | ✅ | — | — |
| [Codex CLI](codex-cli.md) | — | — | — | — | ✅ | — | — |
| Copilot | — | — | — | — | ✅ | — | — |

| Feature | What it means for Observal |
| --- | --- |
| **Skills** | Installable skill packages from the registry — Claude Code's SKILL.md format |
| **Superpowers** | Kiro's equivalent — bundled extensions (`.kiro/skills/`, steering, hooks) |
| **Hook bridge** | IDE fires lifecycle events that Observal consumes (via HTTP or shell `curl`) |
| **MCP servers** | IDE supports MCP; `observal scan` can instrument them |
| **Rules** | IDE loads a text file for system instructions (`AGENTS.md` / `CLAUDE.md`) |
| **Steering files** | Kiro's expanded form — YAML-frontmatter markdown with inclusion modes |
| **OTLP telemetry** | IDE natively exports OpenTelemetry traces and logs |

Source of truth: [`observal_cli/constants.py`](https://github.com/BlazeUp-AI/Observal/blob/main/observal_cli/constants.py).

## Recommended reading order

1. **[Claude Code](claude-code.md)** — the most complete integration. Use this as the reference for what "fully supported" means.
2. **[Kiro](kiro.md)** — also fully supported, but works around the lack of native OTLP via hooks.
3. The others — MCP-only or rules-only at the moment. Contributions welcome.

## If your IDE isn't listed

Two paths:

* **If it supports MCP** — `observal scan` will probably work. Open an issue noting the IDE and its MCP config path.
* **If it supports OTEL** — point `OTEL_EXPORTER_OTLP_ENDPOINT` at `http://localhost:4318` and traces should flow via the OTEL collector.

Either way, [GitHub Discussions](https://github.com/BlazeUp-AI/Observal/discussions) is the place to surface it.
