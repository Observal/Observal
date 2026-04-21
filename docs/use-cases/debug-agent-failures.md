# Debug agent failures

A user says the agent "didn't work." Without traces, you guess. With traces, you walk the exact sequence of events.

## The workflow

1. Find the session.
2. Find the failing trace inside it.
3. Walk the spans.
4. Inspect the failure span — tool name, input, output, error.
5. Reproduce locally, if needed.

## 1. Find the session

Web UI: `http://localhost:3000/traces` → filter by IDE, user, and time range. Click a session to open every trace in it.

CLI:

```bash
observal ops traces --type agent --agent <agent-id> --limit 50
```

Every trace belongs to a `session_id`. Related traces (all from the same IDE session) share it.

## 2. Find the failing trace

In the web UI the trace list colors errored traces red. In the CLI:

```bash
observal ops traces --agent <agent-id> --limit 50
```

Look for non-zero error counts in the summary.

## 3. Walk the spans

```bash
observal ops spans <trace-id>
```

Output is hierarchical — parent span first, then children indented. Each line includes name, duration, status, and error. The failure jumps out.

Example failure walk:

```
trace 9a31...  agent: code-reviewer
├── span: UserPromptSubmit           ok       1ms
├── span: PreToolUse (github_mcp:pr) ok       0ms
├── span: github_mcp:get_pr          ERROR    2412ms
│     error: 404 Not Found — PR #5022 does not exist
├── span: PostToolUse                ok       0ms
└── span: Stop                       ok       0ms
```

In 10 seconds you know: the user asked about a PR that doesn't exist, the MCP call returned 404, the agent stopped. The agent wasn't broken — the input was.

## 4. Inspect the span in detail

The web UI span viewer shows the full input/output payload (pretty-printed JSON). On the CLI, open the span in the web UI via the link at the top of `observal ops spans`, or query GraphQL directly for the raw payload.

## 5. Common failure patterns

| Pattern in spans | Likely cause |
| --- | --- |
| Same tool called 3+ times with identical args | Agent stuck in a loop. Prompt issue or tool result not being consumed. |
| Long latency on one MCP call | External service slow/rate-limited. Check MCP server health. |
| Tool returns success but agent "can't find" the result | Output format the agent doesn't parse. Prompt or tool schema mismatch. |
| Consistent failures only for one user | Env var / auth / permissions issue. Check the user's install config. |
| Agent never calls a tool you expect | Prompt isn't referencing it, or the tool is missing from the agent's config. |

## Alerts: find failures before users report them

Create an alert rule in the web UI (`/settings/alerts`) or via the API. Rules fire on patterns like:

* Error rate for MCP `github-mcp` exceeds 10% over 15 minutes
* P95 latency for agent `code-reviewer` exceeds 8s
* An agent session produces zero tool calls (probably broken)

Alerts feed into your on-call channel via webhook.

## When the trace isn't enough

* **Enable debug logging on the CLI**: `observal --debug ...`
* **Tail server logs**: `docker logs -f observal-api`
* **Check the telemetry buffer**: `observal ops telemetry status`. If the buffer is large, traces may be delayed — the server was unreachable.
* **Confirm the shim is actually wired up**: `observal doctor --ide claude-code`. Missed instrumentation = missing traces.

## Next

→ [Evaluate and compare agents](evaluate-agents.md) — once you've fixed a bug, prove the next version is actually better.
