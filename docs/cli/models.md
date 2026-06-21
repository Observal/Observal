<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal registry models

Display registry-backed harness model data.

## Synopsis

```bash
observal registry models [--harness <name>] [--output table|json|plain]
observal registry models list [--harness <name>] [--output table|json|plain]
```

## Options

| Option | Description |
| --- | --- |
| `--harness <name>` | Filter to one harness, such as `claude-code`, `cursor`, or `pi`. |
| `--output, -o <format>` | Output format: `table` (default), `json`, or `plain`. |

## Data source

The command reads the harness model JSON files packaged with Observal under `observal_shared/harness_models/`.

## Examples

```bash
observal registry models
observal registry models --harness pi --output plain
observal registry models list --harness claude-code --output json
```
