<!-- SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Contribution workflow

The end-to-end path for landing a change in Observal. Discord is the primary
channel for discussion (`discord.observal.io`); GitHub issues and pull requests
are for concrete, actionable items.

## 1. Fork and clone

There is no direct push access. Fork `Observal/Observal` on GitHub, then:

```bash
git clone https://github.com/YOUR-USERNAME/Observal.git
cd Observal
git remote add upstream https://github.com/Observal/Observal.git
```

Push topic branches to your fork (`origin`); never to `upstream`.

## 2. Run the stack locally

Prerequisites: Docker + Docker Compose, uv (Python 3.11+), Node.js 20+ and
pnpm, Git. No configuration is needed for local development; defaults work.

```bash
cp .env.example .env
make rebuild-fast    # build shared API image, reuse for api/init/worker, build web
```

Use `make rebuild` only when the Compose topology changes (new services, build
contexts, image names, volumes, or networks). Use `make rebuild-fast` for
normal backend, frontend, schema, migration, init, or worker changes. The stack
serves at `http://localhost` (nginx on port 80); `.env.example` seeds demo
accounts on first startup.

Frontend only:

```bash
cd web && pnpm install && pnpm dev
```

## 3. Find and claim work

- Check open issues first; `good first issue` is the place to start.
- For larger changes, open an issue or discuss in `#contributing` on Discord before writing code.
- Comment `/take` on a `good first issue` or `help wanted` issue to self-assign; `/drop` to release it.
- Maximum 2 open assigned issues at a time. Issues idle for 30 days are auto-unassigned.
- Issues labeled `keep open` cannot be claimed; anyone may submit a PR for them without assignment.

## 4. Branch

Never commit directly to `main`. Name the branch after the change, using a
Conventional-Commit-aligned prefix. Documented and observed prefixes:

```
feature/skill-registry      # or feat/...
fix/clickhouse-insert-timeout
docs/update-setup-guide
refactor/cli-output-modes
ci/codecov-canonical-upload
chore/release-v1.12.1
```

```bash
git fetch upstream
git switch -c feature/short-topic upstream/main
```

## 5. Make the change, then verify

Install hooks first, then format, lint, and test. All must pass before pushing.

```bash
make hooks     # install pre-commit hooks (do this first)
make format    # auto-format Python (ruff) and TypeScript
make lint      # run all linters (ruff, hadolint, ...)
make test      # quick; use `make test-v` for verbose
```

Include tests for any feature or bug fix. Tests mock external services, so
Docker is not required to run them. See details in
[conventions-and-standards.md](conventions-and-standards.md).

## 6. Rebase, push, open the PR

```bash
git fetch upstream && git rebase upstream/main
git push -u origin feature/short-topic
```

Open the pull request from `your-fork:feature/short-topic` into `Observal:main`.
Then:

1. Fill in the pull request template completely; placeholder or empty sections get the PR closed. See [issue-and-pr-templates.md](issue-and-pr-templates.md).
2. Add a `[Unreleased]` entry in `CHANGELOG.md` if the change is user-facing.
3. Ensure CI passes: linters, tests, and the docker build.
4. Sign the CLA when the CLA-assistant bot prompts you (once per contributor).
5. Respond to review feedback promptly; every PR is evaluated under the Code Review Standard (`docs/code-review.md`).
