# observal config

Local CLI configuration. Config lives in `~/.observal/config.json`; aliases in `~/.observal/aliases.json`.

## Subcommands

| Command | Description |
| --- | --- |
| [`config show`](#observal-config-show) | Show current config (API key masked) |
| [`config set`](#observal-config-set) | Set a config value |
| [`config path`](#observal-config-path) | Print the config file path |
| [`config alias`](#observal-config-alias) | Create a shorthand for an ID |
| [`config aliases`](#observal-config-aliases) | List all aliases |

---

## `observal config show`

Dumps your current config, with the API key masked.

```bash
observal config show
```

Example:

```
server_url:    https://observal.your-company.internal
access_token:  ey••••••••••••••••••••6e
user_id:       f9f3...
user_name:     alice@example.com
output:        table
color:         auto
timeout:       30
```

---

## `observal config set`

Set one config key.

### Synopsis

```bash
observal config set <key> <value>
```

### Common keys

| Key | Purpose |
| --- | --- |
| `server_url` | Observal server base URL |
| `output` | Default output format: `table`, `json`, `plain` |
| `color` | `auto`, `always`, `never` |
| `timeout` | HTTP timeout in seconds |

Example:

```bash
observal config set server_url https://observal.your-company.internal
observal config set timeout 60
```

Login-managed keys (`access_token`, `refresh_token`, `user_id`, `user_name`) are updated by `observal auth login`, not by `config set`.

---

## `observal config path`

Print the path to the config file.

```bash
observal config path
# /Users/alice/.observal/config.json
```

---

## `observal config alias`

Create a shorthand for a long ID. Use the alias anywhere a `<id-or-name>` is accepted, prefixed with `@`.

### Synopsis

```bash
observal config alias <name> <id>
```

### Example

```bash
observal config alias my-mcp 498c17ac-1234-4567-89ab-cdef01234567

observal registry mcp show @my-mcp
observal ops metrics @my-mcp --type mcp
```

Aliases live in `~/.observal/aliases.json`. They're local to your machine.

---

## `observal config aliases`

List every alias you've created.

```bash
observal config aliases
# @my-mcp     → 498c17ac-1234-4567-89ab-cdef01234567
# @reviewer   → a01c5-...
```

## Related

* [Config files](../reference/config-files.md) — full schema of `~/.observal/`
* [Environment variables](../reference/environment-variables.md) — env-var overrides
