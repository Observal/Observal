# Quickstart

Go from zero to "my first trace in the Observal dashboard" in about five minutes. This assumes you've [installed the CLI](installation.md) and have Docker running.

By the end of this guide you will have:

* An Observal server running locally
* The CLI logged in as an admin
* At least one MCP server instrumented
* A live trace visible in the web UI

## 1. Start the server

```bash
git clone https://github.com/BlazeUp-AI/Observal.git
cd Observal
cp .env.example .env

docker compose -f docker/docker-compose.yml up --build -d
```

That's it. The `.env.example` ships with working defaults. Eight containers come up:

| Service | URL |
| --- | --- |
| API (FastAPI) | `http://localhost:8000` |
| Web UI (Next.js) | `http://localhost:3000` |
| Postgres | `localhost:5432` |
| ClickHouse | `localhost:8123` |
| Redis | `localhost:6379` |
| Worker | internal |
| OTEL Collector | `localhost:4317` (gRPC), `4318` (HTTP) |
| Grafana | `http://localhost:3001` |

The API waits for Postgres, ClickHouse, and Redis to pass health checks before starting — expect 15–30 seconds. Confirm it is up:

```bash
curl http://localhost:8000/health
# → {"status": "ok"}
```

Hitting a port conflict? See [Self-Hosting → Ports and volumes](../self-hosting/ports-and-volumes.md).

## 2. Log in

```bash
observal auth login
```

Prompts:

1. **Server URL** — press Enter for `http://localhost:8000`
2. **Login method** — pick `[E]mail`
3. **Email / password** — use one of the seeded demo accounts:

| Role | Email | Password |
| --- | --- | --- |
| Super Admin | `super@demo.example` | `super-changeme` |
| Admin | `admin@demo.example` | `admin-changeme` |
| Reviewer | `reviewer@demo.example` | `reviewer-changeme` |
| User | `user@demo.example` | `user-changeme` |

Log in as super admin for the fewest restrictions while exploring. Credentials land in `~/.observal/config.json` (mode `0600`).

Check it worked:

```bash
observal auth whoami
# → super@demo.example (super_admin)
```

## 3. Instrument your IDE

If you already have MCP servers configured in Claude Code, Kiro, Cursor, VS Code, or Gemini CLI, one command wires them all up:

```bash
observal scan
```

Expected output:

```
Scanning Claude Code config...
  ✓ filesystem        wrapped  (was: npx @modelcontextprotocol/server-filesystem)
  ✓ github            wrapped  (was: npx @modelcontextprotocol/server-github)

Scanning Kiro config...
  ✓ mcp-obsidian      wrapped

Backup saved: ~/.claude/settings.json.20260421_143055.bak
3 server(s) instrumented across 2 IDE(s).
```

What `scan` did:

* Found your existing MCP config files (`~/.claude/settings.json`, `.kiro/settings/mcp.json`, `.cursor/mcp.json`, etc.)
* Registered each MCP server with Observal
* Rewrote the config so every server runs through `observal-shim` (transparent — no behavior change)
* Saved a timestamped `.bak` next to every file it touched

Nothing broke. Your agents still work exactly as before. The only difference: every tool call now generates a span.

Restart your IDE to pick up the new config. The next MCP call will produce a trace.

## 4. See your first trace

Open `http://localhost:3000/traces` in your browser. Trigger anything in your IDE that uses an MCP tool (ask Claude to list files, read a GitHub issue, whatever). Refresh — you'll see the trace appear.

Or use the CLI:

```bash
observal ops traces --limit 5
```

Drill in:

```bash
observal ops spans <trace-id>
```

## 5. (Optional) Pull an agent

Browse what the community has published:

```bash
observal agent list
observal agent show <agent-id>
```

Install one into your IDE:

```bash
observal pull <agent-id> --ide claude-code
```

This drops agent files, skills, hooks, and MCP configs into the right places for your IDE and wires up telemetry automatically.

## What you just built

```
Your IDE  <-->  observal-shim  <-->  MCP server
                      │
                      ▼  (fire-and-forget)
               Observal API  ──►  ClickHouse  ──►  Web UI, eval engine
```

Every MCP request/response is now a span. Spans group into traces. Traces form sessions. The eval engine can score any session.

## Where to next

| You want to... | Go to |
| --- | --- |
| Understand the data model | [Core Concepts](core-concepts.md) |
| Learn what to do with traces | [Use Cases](../use-cases/README.md) |
| Configure the server for production | [Self-Hosting](../self-hosting/README.md) |
| Deep-dive on a CLI command | [CLI Reference](../cli/README.md) |
