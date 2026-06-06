# Cursor Integration

## Overview

Cursor is supported as a first-class IDE in Observal. It provides support for hook bridges, MCP servers, session parsing, and rules-based agent configuration.

## Supported Features

The Cursor integration supports:

* Hook Bridge
* MCP Servers
* Rules
* Session Parsing
* Project and User Scopes

## Installing an Agent

Install an agent for Cursor using:

```bash
observal pull <agent> --ide cursor
```

## Configuration Paths

### Project Scope

| Component   | Path                       |
| ----------- | -------------------------- |
| MCP Servers | `.cursor/mcp.json`         |
| Rules       | `.cursor/rules/{name}.mdc` |
| Hooks       | `.cursor/hooks.json`       |

### User Scope

| Component   | Path                         |
| ----------- | ---------------------------- |
| MCP Servers | `~/.cursor/mcp.json`         |
| Rules       | `~/.cursor/rules/{name}.mdc` |
| Hooks       | `~/.cursor/hooks.json`       |

## Hook Event Mapping

Observal maps internal hook events to Cursor hook events as follows:

| Observal Event   | Cursor Event       |
| ---------------- | ------------------ |
| PreToolUse       | preToolUse         |
| PostToolUse      | postToolUse        |
| Stop             | sessionEnd         |
| SessionStart     | sessionStart       |
| UserPromptSubmit | beforeSubmitPrompt |
| SubagentStop     | subagentStop       |

## MCP Server Support

Cursor MCP server configuration is stored in:

* Project: `.cursor/mcp.json`
* User: `~/.cursor/mcp.json`

The MCP server configuration uses the `mcpServers` key.

## Rules Support

Rules are stored as Markdown Frontmatter files:

* Project: `.cursor/rules/{name}.mdc`
* User: `~/.cursor/rules/{name}.mdc`

## Session Parsing

Cursor uses the built-in `cursor` session parser.

## Caveats and Limitations

* Cursor does not support per-agent model selection.
* Default installation scope is `project`.
* Configuration is stored under the `.cursor` directory.
* Auto model sentinel configuration is not available.
