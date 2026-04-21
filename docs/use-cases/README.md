# Use Cases

Observal solves five concrete problems in the AI-agent lifecycle. Each page below is written as a playbook — what the problem is, how Observal addresses it, and the exact commands to run.

| If you need to... | Read |
| --- | --- |
| See what your MCP servers are actually doing | [Observe MCP traffic](observe-mcp-traffic.md) |
| Package an agent once and ship it to any IDE | [Share agent configs across IDEs](share-agent-configs.md) |
| Know whether your agent is getting better or worse | [Evaluate and compare agents](evaluate-agents.md) |
| Figure out why a session went wrong | [Debug agent failures](debug-agent-failures.md) |
| Give your whole team a source of truth | [Run a team-wide agent registry](team-registry.md) |

## How these relate

```
 Observe  ───►  Debug    (traces give you the evidence)
    │
    ▼
 Evaluate  ──►  Share    (scorecards tell you what works; registry ships it)
    │
    ▼
 Team registry           (ties the loop together for an org)
```

You typically adopt Observal in that order: **observe** first (low-risk, instant value), then **debug**, then **evaluate**, then **share**, and finally **run a team registry** once you have enough published agents to justify governance.
