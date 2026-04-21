# Share agent configs across IDEs

Your team has a reviewer agent that works great in Claude Code. Now someone wants to use it in Kiro. Then Cursor. Then they want to tweak the skills. Copy-pasting config snippets across tools doesn't scale.

Observal's registry gives you one agent definition that installs cleanly into every supported IDE.

## The shape of an agent

Every agent is a YAML file that bundles:

* MCP servers it needs
* Skills to load
* Hooks to wire into the session lifecycle
* Prompts (with variables)
* Sandboxes for code execution

When someone runs `observal pull <agent>`, Observal templates that YAML into the right files for their IDE — `~/.claude/agents/*.json`, `.kiro/agents/*.json`, `.cursor/mcp.json`, and so on.

## Publish an agent

### Option A — the interactive wizard

```bash
observal agent create
```

Step-by-step prompts: name, description, which MCP servers, which skills, which hooks. Results in a registry entry you can share by ID.

### Option B — the YAML workflow (recommended for teams)

```bash
observal agent init                  # scaffold observal-agent.yaml
observal agent add mcp github-mcp    # add components
observal agent add skill code-review-skill
observal agent add hook pretooluse-logger

observal agent build                 # validate (dry-run)
observal agent publish               # submit to registry
```

The YAML workflow is PR-reviewable. The file lives in your repo; changes flow through your normal review process.

## Install an agent into any IDE

Browse what exists:

```bash
observal agent list
observal agent list --search review
observal agent show <agent-id>
```

Install — one command, pick the IDE:

```bash
observal pull <agent-id> --ide claude-code
observal pull <agent-id> --ide kiro
observal pull <agent-id> --ide cursor
observal pull <agent-id> --ide gemini-cli
observal pull <agent-id> --ide vscode
observal pull <agent-id> --ide codex
```

The CLI prompts for any environment variables the MCP servers declare as required (GitHub tokens, API keys). These are stored in your IDE config, not uploaded to Observal.

### Control what gets installed

```bash
# Preview without writing anything
observal pull <agent-id> --ide claude-code --dry-run

# Install into a specific directory
observal pull <agent-id> --ide claude-code --dir ./my-project

# Claude Code only: scope (project-local vs user-global)
observal pull <agent-id> --ide claude-code --scope project
observal pull <agent-id> --ide claude-code --scope user

# Claude Code only: sub-agent model
observal pull <agent-id> --ide claude-code --model sonnet

# Claude Code only: tool allowlist
observal pull <agent-id> --ide claude-code --tools Read,Write,Bash
```

## What portability actually means

The [IDE feature matrix](../integrations/README.md) controls what each IDE supports. If an agent uses skills and the target IDE doesn't have skills, the installer:

* Installs the compatible parts cleanly
* Warns about the unsupported parts
* Exits non-zero if the agent *requires* something the IDE cannot provide

Full compatibility breakdown per IDE lives in [Integrations](../integrations/README.md).

## Snapshot an entire IDE config as a profile

`observal use` and `observal profile` move at a level above single agents — they switch your whole IDE config to a git-hosted or local profile:

```bash
observal use https://github.com/your-org/your-profile.git
observal profile                     # show active profile + backup info
```

Useful when onboarding a new machine or swapping between "work setup" and "personal setup."

## Next

→ [Run a team-wide agent registry](team-registry.md) — once publishing is routine, you need governance.
