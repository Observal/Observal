# Observal: MCP Server & Agent Submission Guide

---

## Part 1: Submitting an MCP Server

### What Observal Expects

When you submit a Git URL, Observal clones the repo and scans for a FastMCP (Python) server. Your repo should look like:

```
your-mcp-server/
├── src/
│   └── server.py          # FastMCP server definition
├── requirements.txt        # or pyproject.toml
└── README.md
```

### Minimum Requirements

Your Python file must contain a FastMCP server:

```python
# server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="your-mcp-server",
    description="A clear description of what this MCP server does (100+ chars recommended)"
)

@mcp.tool()
def search_issues(query: str) -> str:
    """Search for issues matching the query. Returns a list of matching issues with IDs and titles."""
    # Your implementation
    return results

@mcp.tool()
def get_issue(issue_id: int) -> dict:
    """Get full details of a specific issue by ID."""
    # Your implementation
    return issue
```

### Validation Rules

Observal checks:
- Server has a name and description
- Every tool has a description (from docstring or `description` param)
- Every tool has typed input parameters (no bare `**kwargs`)
- Server is importable without runtime errors

### How to Submit

**Via Web UI:**
1. Go to `/mcps` → click **"+ Submit MCP"**
2. Fill in:
   - **Git URL**: `https://github.com/your-org/your-mcp-server.git`
   - **Name**: your-mcp-server
   - **Version**: 1.0.0
   - **Category**: utilities / code-generation / database / devops / testing / documentation / security
   - **Owner**: Your Team
   - **Supported IDEs**: check the IDEs this MCP works with
   - **Description**: 100+ characters describing what the MCP does
3. Click **"Submit for Review"**

**Via CLI:**
```bash
observal submit https://github.com/your-org/your-mcp-server.git
```
Observal auto-detects metadata from the repo and prompts you to confirm/edit.

### What Happens Next

1. Status becomes **pending**
2. Observal runs validation (clone → inspect → manifest check)
3. Admin reviews and approves/rejects
4. Once approved, it appears in the registry for all users

---

## Part 2: Installing an MCP Server

Once an MCP is approved, any user can install it.

### Via Web UI

1. Go to `/mcps` → find the MCP → click **"View"**
2. In the **Install** section, click your IDE (kiro, cursor, claude-code, etc.)
3. Click **"Generate Config"**
4. Click **⬇ Download** to get the config file

### Via CLI

```bash
observal install <mcp-id> --ide kiro
```

### Where to Put the Config

**Kiro:**
```
your-project/
└── .kiro/
    └── mcp.json          ← paste or merge the downloaded config
```

The `mcp.json` looks like:
```json
{
  "mcpServers": {
    "your-mcp-server": {
      "command": "python",
      "args": ["-m", "your-mcp-server"],
      "env": {}
    }
  }
}
```

**Cursor / VS Code:**
```
your-project/
└── .cursor/
    └── mcp.json          ← same JSON format
```

**Claude Code:**
Run the shell command:
```bash
claude mcp add your-mcp-server: python -m your-mcp-server
```

**Gemini CLI:**
Add to your Gemini settings file:
```json
{
  "mcpServers": {
    "your-mcp-server": {
      "command": "python",
      "args": ["-m", "your-mcp-server"]
    }
  }
}
```

### Install the MCP Dependencies

After placing the config, install the actual MCP server package:

```bash
pip install your-mcp-server
# or if it's from a git repo:
pip install git+https://github.com/your-org/your-mcp-server.git
```

Then restart your IDE. The MCP server will be available to your AI assistant.

---

## Part 3: Creating an Agent

An agent in Observal is **not a Git repo**: it's a configuration object you assemble:

```
Agent = System Prompt + MCP Servers + Model Config + Goal Template
```

### Agent Components

| Component | What It Is | Example |
|---|---|---|
| **System Prompt** | Instructions for the AI | "You are an incident analyzer. When given an incident ID, produce root cause analysis..." |
| **Registry MCPs** | MCP servers from the Observal registry | jira-mcp, knowledge-graph-mcp |
| **External MCPs** | Any MCP server by command | `npx -y @modelcontextprotocol/server-github` |
| **Model Config** | Which LLM to use | claude-sonnet-4, max_tokens: 4096 |
| **Goal Template** | Expected output structure | Sections: Root Cause, Similar Incidents, Next Steps |

### How to Create

**Via Web UI:**
1. Go to `/agents` → click **"+ Create Agent"**
2. Fill in basic info (name, version, owner, model)
3. Write the system prompt (50+ chars)
4. Write the description (100+ chars)
5. **Select IDEs**: check which IDEs this agent supports
6. **Link Registry MCPs**: check any approved MCPs from the registry
7. **Add External MCPs**: click "+ Add External MCP" for any MCP not in the registry:
   - **Name**: `github` 
   - **Command**: `npx`
   - **Args**: `-y @modelcontextprotocol/server-github`
   - **Source URL**: `https://github.com/modelcontextprotocol/servers`
8. **Define Goal Template**: what the agent should produce:
   - Add sections (e.g., "Root Cause", "Recommendations")
   - Check "Grounding" if the section must cite sources
9. Click **"Create Agent"**

**Via CLI:**
```bash
observal agent create
# Interactive prompts walk you through each field
```

### Common External MCPs

From [github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers):

| MCP | Command | Args |
|---|---|---|
| GitHub | `npx` | `-y @modelcontextprotocol/server-github` |
| Filesystem | `npx` | `-y @modelcontextprotocol/server-filesystem /path/to/dir` |
| PostgreSQL | `npx` | `-y @modelcontextprotocol/server-postgres postgresql://...` |
| Slack | `npx` | `-y @modelcontextprotocol/server-slack` |
| Google Drive | `npx` | `-y @modelcontextprotocol/server-gdrive` |
| Memory | `npx` | `-y @modelcontextprotocol/server-memory` |
| Puppeteer | `npx` | `-y @modelcontextprotocol/server-puppeteer` |
| Brave Search | `npx` | `-y @modelcontextprotocol/server-brave-search` |

For Python MCPs:

| MCP | Command | Args |
|---|---|---|
| Custom Python MCP | `python` | `-m your_mcp_package` |
| UV-based MCP | `uvx` | `your-mcp-tool` |

---

## Part 4: Installing an Agent

### Via Web UI

1. Go to `/agents` → find the agent → click **"View"**
2. In the **Install** section, click your IDE
3. Click **"Generate Config"**
4. You get two downloadable files:
   - **Rules file** (`.md`): the system prompt, goes in your IDE's rules directory
   - **MCP config** (`.json`): all MCP servers bundled, goes in your IDE's MCP config

### Via CLI

```bash
observal agent install <agent-id> --ide kiro
```

### Where to Put the Files

**Kiro:**
```
your-project/
├── .kiro/
│   ├── rules/
│   │   └── incident-analyzer.md    ← download the rules file here
│   └── mcp.json                     ← merge the MCP config here
```

**Cursor:**
```
your-project/
├── .rules/
│   └── incident-analyzer.md         ← rules file
└── .cursor/
    └── mcp.json                      ← MCP config
```

**Claude Code:**
```bash
# Place the rules file
cp incident-analyzer.md .claude/rules/

# Run the MCP setup commands (shown in the install output)
claude mcp add jira-mcp: python -m jira_connector
claude mcp add github: npx -y @modelcontextprotocol/server-github
```

**Gemini CLI:**
```
your-project/
├── GEMINI.md                         ← rules file (system prompt)
└── .gemini/
    └── settings.json                 ← MCP config
```

### Install MCP Dependencies

After placing the config files, install the actual MCP server packages:

```bash
# For Python MCPs from the registry
pip install jira-mcp knowledge-graph-mcp

# For npm-based external MCPs: no install needed
# npx downloads them automatically on first use

# For Python MCPs from git
pip install git+https://github.com/your-org/your-mcp.git
```

Restart your IDE. The agent's system prompt will guide the AI, and all configured MCP servers will be available as tools.

---

## Quick Reference

| Action | Web UI | CLI |
|---|---|---|
| Submit MCP | `/mcps` → "+ Submit MCP" | `observal submit <git-url>` |
| Install MCP | `/mcps/{id}` → Install → Download | `observal install <id> --ide kiro` |
| Create Agent | `/agents` → "+ Create Agent" | `observal agent create` |
| Install Agent | `/agents/{id}` → Install → Download | `observal agent install <id> --ide kiro` |
| Browse MCPs | `/mcps` | `observal list` |
| Browse Agents | `/agents` | `observal agent list` |
