<!-- SPDX-FileCopyrightText: 2026 Ai-chan-0411 <aoikabu12@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Luca Magrini <lucamagrini1234@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Contributing to Observal

Thank you for considering contributing to Observal. Contributions of all kinds are welcome: bug reports, bug fixes, new features, documentation improvements, and tests.

> [!TIP]
> This page is a quick-start summary. For the full setup walkthrough, architecture notes, and detailed workflows, see the [Development Guide](docs/DEVELOPMENT_GUIDE.md). For new Python tests, follow the [Testing Guide](docs/testing/Testing_Guide.md).

> [!IMPORTANT]
> **Discord is our primary communication channel.** Join at [discord.observal.io](https://discord.observal.io) and ask questions in **#contributing**, report bugs in **#bug**, or discuss ideas in **#feature-requests**. GitHub issues and PRs are for concrete, actionable items, not exploratory discussion.

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) and [AI Policy](AI_POLICY.md) before contributing.

> Parts of this guide were inspired by the contributing documentation from [AnkiDroid/Anki-Android](https://github.com/ankidroid/Anki-Android). They set a great standard for OSS contributor docs and were one of the first open-source projects some of our maintainers were part of. If you are looking for another welcoming OSS project, check them out.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Finding Work](#finding-work)
- [Making Changes](#making-changes)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Reporting Issues](#reporting-issues)
- [Enterprise Directory](#enterprise-directory-ee)
- [License](#license)
- [CLA](#contributor-license-agreement-cla)

---

## Getting Started

### Prerequisites

- Docker and Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python 3.11+)
- Node.js 20+ and pnpm (for the web frontend)
- Git

### Fork and Clone

```bash
git clone https://github.com/YOUR-USERNAME/Observal.git
cd Observal
git remote add upstream https://github.com/Observal/Observal.git
```

### Running Locally

No configuration needed for local development. All settings have working defaults.

**Full stack (Docker):**

```bash
cp .env.example .env
make rebuild-fast
```

For normal backend, frontend, and dependency changes, use `make rebuild-fast`. It builds the shared API image once, reuses it for the API, init, and worker services, then builds the web image.

Use `make rebuild` when the Compose topology changes, such as adding services, changing build contexts, changing image names, or updating volumes and networks.

For schema, migration, ClickHouse setup, init path, or worker changes, use `make rebuild-fast` so the shared API image used by `observal-init` and `observal-worker` is refreshed.

Wait for services to be healthy, then:

```bash
uv tool install --editable .
observal auth login
```

The stack starts at `http://localhost` (nginx LB on port 80). The `.env.example` seeds demo accounts on first startup, log in with `super@demo.example` / `super-changeme` for admin access. See [SETUP.md](SETUP.md) for all credentials.

**Frontend only:**

```bash
cd web && pnpm install && pnpm dev
```

Set `NEXT_PUBLIC_API_URL=http://localhost` in `web/.env.local` if the backend is on a different host.

> [!NOTE]
> See the [Development Guide](docs/DEVELOPMENT_GUIDE.md) for the full environment setup and troubleshooting steps.

---

## Finding Work

Check [open issues](https://github.com/Observal/Observal/issues) before starting. Look for **good first issue** if you are new.

For larger changes, open an issue or discuss in **#contributing** on Discord before writing code.

### Claiming Issues

- **`/take`** on any `good first issue` or `help wanted` issue to self-assign.
- **`/drop`** to release an issue you can no longer work on.
- Max **2 open assigned issues** at a time.
- Issues with no activity for **30 days** are automatically unassigned.

> [!WARNING]
> Issues labeled `keep open` cannot be claimed. Anyone may submit a PR for those without assignment.

---

## Making Changes

### Branch Naming

```
feature/skill-registry
fix/clickhouse-insert-timeout
docs/update-setup-guide
```

Never commit directly to `main`.

### Code Style

```bash
make hooks     # install pre-commit hooks (do this first)
make format    # auto-format Python and TypeScript
make lint      # run all linters
```

Python is formatted with `ruff`. Dockerfiles with `hadolint`. Pre-commit hooks enforce both.

### SPDX Headers

Every source file needs SPDX headers. The pre-commit hook adds them automatically.

```python
# SPDX-FileCopyrightText: 2026 Your Name <your@email.com>
# SPDX-License-Identifier: AGPL-3.0-only
```

Use `// ` for TypeScript, `<!-- -->` for Markdown. CI will block merge if any file is missing headers.

### Testing

```bash
make test      # quick
make test-v    # verbose
```

All tests must pass before submitting. Tests mock all external services so Docker is not required. Include tests for any feature or bug fix.

New Python tests should follow the [Testing Guide](docs/testing/Testing_Guide.md). In short, keep tests hermetic, assert behavior over implementation details, use small local helpers for setup, and avoid touching real user configuration.

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(cli): add skill submit command
fix(telemetry): handle null span timestamps
docs: update contributing guide
```

Subject line under 72 characters, imperative mood, no trailing period.

### Changelog

Add an entry under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md) for any user-facing change.

---

## Submitting a Pull Request

> [!IMPORTANT]
> Read the [AI Policy](AI_POLICY.md) before submitting. AI-assisted contributions are welcome but must meet the standards described there. **Autonomous coding agents (Devin, SWE-agent, OpenHands, and similar tools that write and submit code without meaningful human authorship) are not permitted**, see the AI Policy for the legal and practical reasons. PRs that show obvious signs of unreviewed AI output will be closed without review.

1. Rebase against `main` before opening:
    ```bash
    git fetch upstream && git rebase upstream/main
    ```
2. Push your branch and open a PR against `main`.
3. Fill in the PR template completely. PRs with unfilled or placeholder sections will be closed.
4. Ensure CI passes (linters, tests, docker build).
5. Add a changelog entry if your change is user-facing.
6. Respond to review feedback promptly.

Keep PRs focused on a single concern. Smaller PRs are easier to review and faster to merge.

---

## Reporting Issues

### Bugs

Search [existing issues](https://github.com/Observal/Observal/issues) first. Include:

- Steps to reproduce
- Expected vs actual behaviour
- OS, Python, Node.js, Docker versions
- Error logs or screenshots

### Feature Requests

Describe the problem you are solving, not just the solution. Discuss in **#feature-requests** on Discord first for larger features.

---

## Enterprise Directory (`ee/`)

> [!CAUTION]
> Community contributions are **not accepted** into `ee/`. Pull requests touching `ee/` files will be closed. The open-source core must never import from `ee/`.

The `ee/` directory is licensed under the [Observal Enterprise License](ee/LICENSE). The dependency is strictly one-way: `ee/` may import from the core, never the reverse.

---

## License

All code outside `ee/` is licensed under [AGPL-3.0](LICENSE). The `ee/` directory is licensed under the [Observal Enterprise License](ee/LICENSE).

---

## Contributor License Agreement (CLA)

The [CLA-assistant](https://cla-assistant.io) bot will prompt you to sign the [Observal CLA](CLA.md) on your first PR. You only need to sign once. For corporate contributions, contact contact@observal.io.
