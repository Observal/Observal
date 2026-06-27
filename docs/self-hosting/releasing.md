<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Releasing

How to cut a release of Observal. This is for maintainers with push access.

## Prerequisites

- A fork of `Observal/Observal` with `origin` pointing to your fork and `upstream` pointing to the org repo
- GitHub CLI (`gh`) installed and authenticated
- `git-cliff` installed (`cargo install git-cliff`) or `uvx` available as a fallback

## Quick reference

```bash
make release-patch     # 0.1.0 -> 0.1.1
make release-feature   # 0.1.0 -> 0.2.0
make release-major     # 0.1.0 -> 1.0.0
```

That's it. One command. The script bumps versions, generates the changelog, commits, pushes a release branch to your fork, and opens a PR. Merging the PR triggers the release pipeline automatically.

## What happens when you run the command

1. `tools/release.sh` verifies you're on `main` and in sync with `upstream/main`
2. Creates a `release/vX.Y.Z` branch
3. Bumps the version in both `pyproject.toml` (CLI) and `observal-server/pyproject.toml` (server)
4. `git-cliff` regenerates `CHANGELOG.md` from conventional commits
5. A signed commit (`bump(release): vX.Y.Z`) is created
6. The branch is pushed to your fork and a PR is opened against `upstream/main`

## What happens when the PR merges

The release workflow detects the `bump(release): vX.Y.Z` commit on main, creates an annotated tag, and triggers the build pipeline.

These jobs run in parallel:

| Job | What it produces |
|-----|-----------------|
| `cli-binaries` | Standalone CLI binaries for 6 platforms (Linux/macOS/Windows, x64/arm64) via PyInstaller |
| `docker-images` | Multi-arch Docker images pushed to `ghcr.io/observal/observal-api` and `ghcr.io/observal/observal-web` |
| `server-package` | Deployment tarball (`observal-server-vX.Y.Z.tar.gz`) with Docker Compose, configs, and setup script |
| `pypi` | Python package published to PyPI via Trusted Publishing |

After all jobs complete, the workflow pauses at the `production` environment approval gate. A maintainer must click "Approve" in the GitHub Actions UI before the release publishes.

The final `release` job:
- Downloads all artifacts
- Generates SHA256 checksums (`checksums.txt`)
- Generates release notes from git-cliff
- Creates SLSA build provenance attestation
- Creates a draft GitHub Release with all assets and contributor attribution
- Publishes the release (removes draft status)

## When to use which bump type

| Type | When | Examples |
|------|------|---------|
| `patch` | Bug fixes, dependency updates, docs, CI tweaks | Fix login redirect, update ruff version, typo in docs |
| `feature` | New functionality, new endpoints, new CLI commands | Add SAML support, add audit log viewer, new alert rule type |
| `major` | Breaking changes, major rewrites, incompatible API changes | Auth system rewrite, database schema migration required, CLI flag rename |

## Conventional commits

The changelog is generated from commit messages. Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add SAML SSO support
fix: correct redirect URL in OAuth callback
docs: update self-hosting guide
chore: bump dependencies
perf: optimize ClickHouse batch inserts
refactor: extract audit helper from event bus
ci: add PyInstaller binary builds
test: add SAML configuration tests
```

Commits prefixed with `bump(release):` are automatically excluded from the changelog.

## What end users see

### CLI users

```bash
curl -fsSL https://raw.githubusercontent.com/Observal/Observal/main/install.sh | bash
```

Downloads the right binary for their OS/arch, verifies the checksum, and installs to `/usr/local/bin/observal`. Or `pip install observal` for Python users.

### Server deployers

```bash
curl -fsSL https://raw.githubusercontent.com/Observal/Observal/main/install-server.sh | bash
```

Downloads the server tarball, unpacks to `/opt/observal`, and runs an interactive setup that prompts for deployment mode, frontend URL, and auto-generates database passwords. Starts the full Docker Compose stack.

## Configuration

The release script defaults to `upstream` for the org repo and `origin` for your fork. Override with environment variables if your remotes are named differently:

```bash
OBSERVAL_UPSTREAM=org OBSERVAL_FORK=myfork make release-patch
```

## Access control

Three layers prevent unauthorized releases:

1. **Branch protection on main**: PRs required with status checks, so the release commit must pass review
2. **Tag protection rules**: Only the release workflow (via `GITHUB_TOKEN`) creates `v*` tags
3. **Environment gate**: The `production` environment requires authorized reviewers to approve major/feature releases

## Troubleshooting

### Release script fails with "Working tree is dirty"

Commit or stash your changes first. The release script requires a clean working tree.

### Release script fails with "Releases must be cut from main"

Switch to `main` and ensure it's up to date: `git checkout main && git pull upstream main`

### Release script fails with "not up to date with upstream/main"

Pull latest: `git pull upstream main`

### CI workflow doesn't trigger after PR merge

The workflow looks for a commit message matching `bump(release): vX.Y.Z`. If the PR was squash-merged with a different message, the workflow won't detect it. Use "Rebase and merge" or "Create a merge commit" when merging release PRs.

### Approval gate not appearing

Ensure the `production` environment exists in GitHub Settings > Environments and has required reviewers configured.

### PyPI publish fails

Verify that PyPI Trusted Publishing is configured: PyPI > Project > Publishing > Trusted Publisher with `owner=Observal`, `repo=Observal`, `workflow=release.yml`, `environment=pypi`.

### Docker push fails

GHCR authentication uses `GITHUB_TOKEN` automatically. If it fails, check that the repository's Actions permissions allow writing packages (Settings > Actions > General > Workflow permissions).
