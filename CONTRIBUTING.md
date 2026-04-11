# Contributing to Observal

Contributions of all kinds are welcome: bug fixes, new features, documentation improvements.

## Fork and Clone

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

## Development Environment

Requirements:

- Docker and Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python 3.11+)
- Node.js 20+ and pnpm (for the web frontend)
- Git

## Running Locally

```bash
cp .env.example .env
# edit .env with your values

cd docker
docker compose up --build -d
cd ..

uv tool install --editable .
observal init
```

The API starts at http://localhost:8000.

### Frontend

```bash
cd web
pnpm install
pnpm dev
```

The web UI starts at http://localhost:3000. Set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `web/.env.local` if the backend is on a different host.

See [SETUP.md](SETUP.md) for detailed configuration and troubleshooting.

## Code Style

Python is linted and formatted with `ruff`. Docker files are linted with `hadolint`. Pre-commit hooks enforce both.

```bash
make format   # auto-format
make lint     # run linters
make hooks    # install pre-commit hooks
```

## Running Tests

```bash
make test     # quick
make test-v   # verbose
```

All tests must pass before submitting a PR. Tests mock all external services: no Docker needed.

## Branch Naming

Do not commit directly to `main`. Use prefixes:

- `feature/` for new features
- `fix/` for bug fixes
- `docs/` for documentation

```
feature/skill-registry
fix/clickhouse-insert-timeout
docs/update-setup-guide
```

## Commit Messages

Follow conventional commits:

```
<type>(<scope>): <description>
```

```
feat(cli): add skill submit command
fix(telemetry): handle null span timestamps
docs: update contributing guide
```

### DCO Sign-off

All commits must include a `Signed-off-by` line to certify the [Developer Certificate of Origin (DCO)](https://developercertificate.org/). This confirms that you wrote (or have the right to submit) your contribution and that it is licensed under the project's GNU AGPL v3.0 license.

Add the sign-off automatically with the `-s` flag:

```bash
git commit -s -m "feat(cli): add skill submit command"
```

This appends a line like:

```
Signed-off-by: Your Name <your.email@example.com>
```

Make sure your `user.name` and `user.email` in git config match the identity you want to use. A CI check will block PRs that have unsigned commits.

## Changelog

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

## Pull Request Process

1. Push your branch to your fork.
2. Open a PR against `main`.
3. Ensure linters and tests pass.
4. Ensure all commits are signed off (`git commit -s`).
5. Add a changelog entry if your change is user-facing.
5. Respond to review feedback and update your code if requested.

## Issues

Check existing issues before starting work. For bug reports, include reproduction steps and environment details. For feature requests, describe the use case clearly. Discuss major features in an issue before implementing.

## Codebase Context

See [AGENTS.md](AGENTS.md) for internal architecture notes, file layout, and conventions. This is especially useful when working with AI coding agents.

## License

By contributing, you agree that your contributions will be licensed under the GNU Affero General Public License v3.0. The DCO sign-off on each commit is your explicit acknowledgement of this.
