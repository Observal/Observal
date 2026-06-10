<!-- SPDX-FileCopyrightText: 2026 Ai-chan-0411 <aoikabu12@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 DoomsCoder <vedantkakade05@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

<pre>
 ██████╗ ██████╗ ███████╗███████╗██████╗ ██╗   ██╗ █████╗ ██╗
██╔═══██╗██╔══██╗██╔════╝██╔════╝██╔══██╗██║   ██║██╔══██╗██║
██║   ██║██████╔╝███████╗█████╗  ██████╔╝██║   ██║███████║██║
██║   ██║██╔══██╗╚════██║██╔══╝  ██╔══██╗╚██╗ ██╔╝██╔══██║██║
╚██████╔╝██████╔╝███████║███████╗██║  ██║ ╚████╔╝ ██║  ██║███████╗
 ╚═════╝ ╚═════╝ ╚══════╝╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚═╝  ╚═╝╚══════╝
</pre>

**A self-hosted unified agent registry with built in analytics. Enterprise edition adds SSO (OIDC and SAML), Audit Logs, Security Events and organizational AI insights.**

<p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python">
  <a href="https://pypi.org/project/observal-cli/"><img src="https://img.shields.io/pypi/v/observal-cli?style=flat-square&logo=pypi&logoColor=white&label=pypi" alt="PyPI version"></a>
  <a href="https://codecov.io/gh/BlazeUp-AI/Observal"><img src="https://img.shields.io/codecov/c/github/BlazeUp-AI/Observal?style=flat-square&logo=codecov" alt="Coverage"></a>
  <a href="https://github.com/BlazeUp-AI/Observal/graphs/contributors"><img src="https://img.shields.io/github/contributors/BlazeUp-AI/Observal?style=flat-square&logo=github" alt="Contributors"></a>
  <a href="https://discord.observal.io"><img src="https://img.shields.io/badge/discord-chat-5865f2?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/orgs/BlazeUp-AI/packages?repo_name=Observal"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Haz3-jolt/b28aba6d0efebb0b430d43c8068feb91/raw/ghcr-pulls.json&style=flat-square" alt="GHCR pulls"></a>
</p>

> If you find Observal useful, please consider giving it a star. It helps others discover the project and keeps development going.

---

## Supported IDEs

| IDE |
|-----|
| Claude Code |
| Kiro |
| Cursor |
| Pi |
| Copilot (CLI & VS Code Extension) |
| Codex |
| OpenCode |
| Antigravity CLI |

One command to install any agent into any supported IDE. The config files are generated per-IDE automatically.

---

## Quick Start

Observal has two parts: a **server** (API + web UI + databases) you self-host, and a **CLI** you install on each developer machine.

### 1. Deploy the server

**One-line install** (requires Docker Engine ≥ 24.0 with Compose v2):

```bash
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install-server.sh | bash
```

This downloads a Docker Compose package, runs guided setup (domain, secrets, ports), pulls container images from GHCR, and starts the full stack (API, web UI, PostgreSQL, ClickHouse, Redis, worker, load balancer, Prometheus, Grafana).

**From source** (for contributors):

```bash
git clone https://github.com/BlazeUp-AI/Observal.git && cd Observal
cp .env.example .env
make up
```

### 2. Install the CLI

**Standalone binary** (no Python required):

```bash
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install.sh | bash
```

**Python** (3.11+):

```bash
uv tool install observal-cli
# or: pipx install observal-cli
```

### 3. Connect your IDE

```bash
observal auth login
observal doctor --patch
```

This authenticates with your server, detects your IDE, installs telemetry hooks, and starts capturing sessions automatically.

Once logged in, run `/observal` inside your IDE and it takes the wheel. Pull agents, submit components, browse the registry, run diagnostics:

```
/observal pull security-auditor
/observal scan
/observal doctor
```

Or just tell your agent what you want and it figures out the right commands.

---

## What Observal Does

### Agents are the primary unit

An agent bundles 5 component types into a single installable package: **MCP servers**, **skills**, **hooks**, **prompts**, and **sandboxes**. You define them in YAML, publish to the registry, and anyone can pull them with one command. The platform generates the right config files for whichever IDE the user runs.

```bash
observal pull security-auditor --ide pi
```

### Every session becomes a trace

Once connected, Observal captures your entire coding session: every user prompt, every thinking block, every assistant response, every tool call with its full input and output. No sampling, no summarization. The raw session flows into ClickHouse for querying and analysis.

### The registry is a package manager for agents

Browse published agents, see which IDEs they support, check download counts and ratings, and install with one command. Admins review submissions before they go live. Version diffs show exactly what changed between releases.

---

## Agent Registry

**Browse, search, and install agents with IDE compatibility badges:**

![Agent registry with grid view](docs/img/registry.png)

**Build agents visually with live config preview for every IDE:**

![Agent Builder with preview panel](docs/img/builder.png)

**Components library: MCPs, Skills, Hooks, Prompts, Sandboxes:**

![Component registry showing MCP servers](docs/img/component_registry.png)

---

## Session Replay

**Full session overview with token counts, models, tools, and turn-by-turn timeline:**

![Session detail showing tokens, tools, models, and turns](docs/img/ses1.png)

**Every turn captured: user prompt, tool calls, thinking block, assistant response:**

![Turn expanded showing user prompt, thinking, and response](docs/img/complete_capture_thinking_response.png)

**Drill into any span to see exact tool inputs and outputs:**

![Span detail showing bash command input and full output](docs/img/span.png)

---

## Review and Governance

**Admin review queue with full prompt inspection and approve/reject:**

![Review queue with agent detail](docs/img/review.png)

**Version diffs show exactly what changed between releases:**

![Side-by-side diff of v1.0.0 vs v2.0.0](docs/img/review-diff.png)

**Leaderboard tracks top agents and components by downloads:**

![Leaderboard with rankings](docs/img/leaderboard.png)

---

## Agent Insights

**AI-powered insight reports** analyze usage patterns across all sessions — what's working, what's hindering, and quick wins. Powered by [LiteLLM](https://docs.litellm.ai/docs/providers), works with any provider (Anthropic, OpenAI, Bedrock, Gemini, Azure, Ollama).

![Insight report with What's Working, What's Hindering, Quick Wins](docs/img/insights.png)

See [Insights LLM Setup](docs/insights-setup.md) for configuration.

---

## Enterprise Edition

Source-available under a separate license. Activated with a signed JWT key. Core never imports from `ee/`, the open-source edition is fully functional without it.

Enterprise adds:

- **Audit trail/logs** with parameterized search and CSV export
- **SAML SSO** and **SCIM provisioning**
- **Executive dashboard** for org-wide agent performance

**Audit log with parameterized search:**

![Audit log with PHI sensitivity badges and chain hashes](docs/img/audit_logging.png)

The server and CLI are the same package for all editions. Enterprise features activate at runtime when a valid license key is present:

```bash
# Pass the key during server install
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install-server.sh | bash -s -- --license-key YOUR_KEY

# Or add it later to your .env
echo 'OBSERVAL_LICENSE_KEY=your.key' >> .env
make rebuild
```

---

## Documentation

Full docs at **[docs.observal.io](https://docs.observal.io/)**

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16, React 19, Tailwind CSS 4, shadcn/ui |
| Backend | Python 3.11+, FastAPI, Strawberry GraphQL |
| Databases | PostgreSQL 16 (registry), ClickHouse (telemetry) |
| Queue | Redis + arq |
| CLI | Python, Typer, Rich |
| Telemetry | Session hooks, stdio shims, push-based ingest |
| Deployment | Docker Compose (10 services) |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version:

1. Fork and clone
2. `make hooks` to install pre-commit hooks
3. Create a feature branch
4. Run `make lint` and `make test`
5. Open a PR

See [AGENTS.md](AGENTS.md) for internal codebase context.

## Community

[GitHub Discussions](https://github.com/BlazeUp-AI/Observal/discussions) for questions and ideas. [Discord](https://discord.observal.io) for chat. Open Issues for confirmed bugs.

## Reporting Issues

```bash
observal support bundle
```

Produces a redacted diagnostic archive. Review before sharing: `observal support inspect observal-support-*.tar.gz`

For live debugging, Observal uses loguru-based dev logging (internally called "optic"). Stream logs with:

```bash
observal logs
```

Logs are written to `~/.observal/logs/dev.log` and include structured context for every request, background job, and telemetry event.

## Security

Report vulnerabilities via [GitHub Private Vulnerability Reporting](https://github.com/BlazeUp-AI/Observal/security/advisories) or email contact@blazeup.app. Do not open a public issue. See [SECURITY.md](SECURITY.md).

## Star History

<a href="https://www.star-history.com/?repos=BlazeUp-AI%2FObserval&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=BlazeUp-AI/Observal&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=BlazeUp-AI/Observal&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=BlazeUp-AI/Observal&type=date&legend=top-left" />
 </picture>
</a>

## License

GNU Affero General Public License v3.0 (AGPL-3.0). See [LICENSE](LICENSE).
