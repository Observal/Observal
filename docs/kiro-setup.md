<!--
SPDX-FileCopyrightText: 2024 BlazeUp-AI
SPDX-License-Identifier: Apache-2.0
-->

# Kiro IDE Setup Guide for Observal

This guide walks you through setting up Observal with Kiro IDE/CLI.

## Prerequisites

- Kiro IDE or Kiro CLI installed
- Observal running locally (see [SETUP.md](./SETUP.md))
- Python 3.11+
- `uv` installed

## Quick Start

### 1. Install Observal CLI

```bash
uv tool install --editable .
observal init
```

### 2. Scan your Kiro config

```bash
observal scan --ide kiro
```

This auto-detects MCP servers from your Kiro config and wraps them with `observal-shim` for telemetry.

### 3. Dry run first (recommended)

```bash
observal scan --ide kiro --dry-run
```

Preview changes before applying them.

## Installing MCP Servers for Kiro

```bash
observal install <mcp-id> --ide kiro
```

## Installing Skills for Kiro

```bash
observal skill install <skill-id> --ide kiro
```

## Installing Hooks for Kiro

```bash
observal hook install <hook-id> --ide kiro
```

## Telemetry

Kiro does not support native OpenTelemetry. Observal uses a
hook-based telemetry bridge instead. Hooks fire at lifecycle
events and send trace data to Observal automatically.

## Verifying Setup

```bash
observal doctor
```

Check that Kiro-specific diagnostics all pass. ✅

## Troubleshooting

| Problem | Fix |
|---|---|
| `observal scan` finds no Kiro config | Make sure Kiro config exists at `~/.kiro/` |
| Hooks not firing | Re-run `observal install` for hooks |
| Telemetry not showing | Check `observal telemetry status` |

## More Help

- [SETUP.md](./SETUP.md) — General setup
- [GitHub Discussions](https://github.com/BlazeUp-AI/Observal/discussions)
- [Open an issue](https://github.com/BlazeUp-AI/Observal/issues)