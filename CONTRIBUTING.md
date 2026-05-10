# Contributing to Observal

Thank you for considering contributing to Observal! Contributions of all kinds are welcome: bug reports, bug fixes, new features, documentation improvements, and tests. This guide walks you through the process from setting up your environment to getting your pull request merged.

Please note that this project is released with a [Contributor Code of Conduct](CODE_OF_CONDUCT.md). By participating in this project you agree to abide by its terms.

If you have questions about contributing or want to discuss your ideas before opening a PR, join the [Observal Discord](https://discord.observal.io) to chat with the maintainers.

## Table of Contents

- [Getting Started](#getting-started)
- [Finding Work](#finding-work)
- [Making Changes](#making-changes)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Reporting Issues](#reporting-issues)
- [Codebase Context](#codebase-context)
- [License](#license)
- [Contributor License Agreement (CLA)](#contributor-license-agreement-cla)

## Getting Started

### Prerequisites

- Docker and Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python 3.11+)
- Node.js 20+ and pnpm (for the web frontend)
- Git

### Fork and Clone

1. Fork the repository on GitHub.
2. Clone your fork:

```bash
git clone https://github.com/YOUR-USERNAME/Observal.git
cd Observal
```

3. Add the upstream remote:

```bash
git remote add upstream https://github.com/BlazeUp-AI/Observal.git
```

### Running Locally

No configuration needed for local development. All settings have working defaults.

**Full stack (Docker):**

```bash
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build -d
```

Wait for all services to be healthy (`docker compose -f docker/docker-compose.yml ps`), then install the CLI and log in:

```bash
uv tool install --editable .
observal auth login
```

The API starts at http://localhost:8000 and the web UI at http://localhost:3000. The `.env.example` seeds four demo accounts on first startup — log in with `super@demo.example` / `super-changeme` for full admin access. See [SETUP.md](SETUP.md) for all demo credentials and the full step-by-step walkthrough.

**Frontend only (for UI work):**

```bash
cd web
pnpm install
pnpm dev
```

Set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `web/.env.local` if the backend is on a different host.

See [SETUP.md](SETUP.md) for detailed configuration, eval engine setup, and troubleshooting.

## Enterprise Directory (`ee/`)

The `ee/` directory contains proprietary enterprise features licensed under the [Observal Enterprise License](ee/LICENSE). This code is **source-available** but requires a commercial license for production use.

**Community contributions are not accepted into `ee/`.** All code in that directory is written exclusively by the Observal team. Pull requests that modify files under `ee/` will be closed.

If you are unsure whether your change belongs in the open-source core or the enterprise directory, open an issue to discuss it first.

The open-source core must never depend on code in `ee/`. The dependency direction is strictly one-way:

- `ee/` code **can** import from the open-source core
- Open-source code **cannot** import from `ee/`

### Enterprise Setup

To develop or test enterprise features locally, set `DEPLOYMENT_MODE=enterprise` in your `.env` and follow the standard setup in [SETUP.md](SETUP.md). Enterprise mode enables SSO-only authentication, SCIM user provisioning, and audit logging. You will need to configure OAuth/OIDC variables (`OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_SERVER_METADATA_URL`) — see the environment variables table in SETUP.md for details.

## Finding Work

Before starting work, check the [open issues](https://github.com/BlazeUp-AI/Observal/issues) to see what needs attention.

- Look for issues labelled **good first issue** if you are new to the project.
- For larger features or architectural changes, open an issue to discuss your approach before writing code. This avoids wasted effort if the direction needs adjustment.

### Claiming Issues with `/take` and `/drop`

Instead of commenting manually, you can use slash commands to self-assign issues:

- **`/take`** — Comment `/take` on any issue labeled `good first issue` or `help wanted` to assign it to yourself. The bot will confirm the assignment and link you to this contributing guide.
- **`/drop`** — Comment `/drop` on an issue you are assigned to if you can no longer work on it. This frees the issue for other contributors.

**Rules:**

- `/take` only works on issues labeled `good first issue` or `help wanted`.
- Issues labeled `keep open` cannot be assigned — anyone can submit a PR for those without claiming them.
- You can have at most **2 open issues** assigned to you at a time. If you try to take a third, the bot will list your current assignments so you can decide which to `/drop`.
- If an issue is already assigned, `/take` will let you know who is working on it and suggest other available issues.
- **Stale assignment cleanup:** Issues with no activity for 30 days are automatically unassigned. If you need more time, just post a comment with a progress update to reset the timer. You can always `/take` the issue again afterwards.

## Making Changes

### Branch Naming

Do not commit directly to `main`. Create a branch from the latest `main` with one of these prefixes:

- `feature/` for new features
- `fix/` for bug fixes
- `docs/` for documentation

```
feature/skill-registry
fix/clickhouse-insert-timeout
docs/update-setup-guide
```

### Code Style

Python is linted and formatted with `ruff`. Dockerfiles are linted with `hadolint`. Pre-commit hooks enforce both - install them early so issues are caught before you commit.

```bash
make hooks     # install pre-commit hooks
make format    # auto-format
make lint      # run linters
```

### Testing

```bash
make test      # quick
make test-v    # verbose
```

All tests must pass before submitting a PR. Tests mock all external services, so Docker does not need to be running. If you are adding a new feature or fixing a bug, include tests that cover the change.

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>
```

```
feat(cli): add skill submit command
fix(telemetry): handle null span timestamps
docs: update contributing guide
```

Keep the subject line under 72 characters, use the imperative mood ("add", not "added"), and do not end it with a period. If more detail is needed, add a blank line after the subject and write a longer description wrapped at 80 characters.

### DCO Sign-off

All commits must include a `Signed-off-by` line to certify the [Developer Certificate of Origin (DCO)](https://developercertificate.org/). The DCO is a lightweight agreement that confirms you wrote (or have the right to submit) your contribution and that it is licensed under the project's open-source license (AGPL-3.0 for all code outside `ee/`).

You can add the sign-off manually to your commit message:

```
feat(cli): add skill submit command

Signed-off-by: Your Name <your.email@example.com>
```

Or use the `-s` flag to have Git append it for you:

```bash
git commit -s -m "feat(cli): add skill submit command"
```

> **Note:** The project does not configure or encourage automatic sign-off (e.g. via Git hooks or aliases). The DCO sign-off is a conscious attestation that you have the right to submit your contribution. If you choose to automate it, that is your responsibility — you are still bound by its terms.

Make sure your `user.name` and `user.email` in git config match the identity you want to use. A CI check and a pre-push hook will block PRs that have unsigned commits.

### Changelog

We maintain a [CHANGELOG.md](CHANGELOG.md) following the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. When submitting a PR that adds a feature, fixes a bug, or makes any user-facing change, add an entry under the `[Unreleased]` section in the appropriate category:

- **Added** for new features
- **Changed** for changes in existing functionality
- **Deprecated** for soon-to-be removed features
- **Removed** for now removed features
- **Fixed** for bug fixes
- **Security** for vulnerability fixes

Example:

```markdown
## [Unreleased]

### Fixed

- Resolve null span timestamp crash in telemetry ingestion
```

At release time, a maintainer will move unreleased entries into a versioned section.

## Submitting a Pull Request

1. Make sure your branch is up to date with `main`:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```
2. Push your branch to your fork.
3. Open a PR against `main` on the [Observal repository](https://github.com/BlazeUp-AI/Observal).
4. Describe your changes clearly: what you changed and why. Link the related issue if one exists.
5. Ensure CI passes (linters, tests).
6. Ensure all commits are signed off (`git commit -s`).
7. Add a changelog entry if your change is user-facing.
8. Respond to review feedback and update your code if requested.

Keep pull requests focused on a single concern. It is better to open three small PRs that each address one issue than one large PR that mixes unrelated changes. Smaller PRs are easier to review and faster to merge.

## Reporting Issues

### Bug Reports

Search [existing issues](https://github.com/BlazeUp-AI/Observal/issues) first to avoid duplicates. When filing a bug report, include:

- **Steps to reproduce** the problem
- **Expected behaviour** vs **actual behaviour**
- **Environment details**: OS, Python version, Node.js version, Docker version
- **Error logs or screenshots** if applicable

The more detail you provide, the faster the issue can be diagnosed.

### Feature Requests

Describe the use case clearly. Explain the problem you are trying to solve, not just the solution you have in mind. This helps maintainers evaluate the request in the broader context of the project.

## Codebase Context

See [AGENTS.md](AGENTS.md) for internal architecture notes, file layout, and conventions. See [docs/cli/README.md](docs/cli/README.md) for the full CLI command reference. Both are useful for new contributors and AI coding agents alike.

## License

This repository uses a dual-license structure. All code outside the `ee/` directory is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE). The `ee/` directory is licensed separately under the [Observal Enterprise License](ee/LICENSE) and does not accept community contributions.

## Contributor License Agreement (CLA)

Before your first pull request can be merged, you must sign the [Observal CLA](CLA.md). This is handled automatically — when you open a PR, the [CLA-assistant](https://cla-assistant.io) bot will comment with a link to sign electronically. You only need to sign once.

The CLA and the DCO work together. The DCO (signed on every commit) certifies that you wrote the code and have the right to submit it. The CLA grants BlazeUp AI the rights needed to distribute your contribution under both the open-source and commercial licenses.

If you are contributing on behalf of a company, contact contact@observal.io to arrange a Corporate CLA.
