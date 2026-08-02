<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Releasing

How maintainers cut a curated Observal release.

## Prerequisites

- A fork with `origin` pointing to the fork and `upstream` pointing to `Observal/Observal`
- GitHub CLI authenticated with repository access
- `uv` and Git
- A clean local `main` that exactly matches `upstream/main`

The release tool uses the existing `questionary` project dependency. git-cliff is not used.

## Prepare a release

```bash
make release
```

For a no-write rehearsal:

```bash
make release-preview
```

The tool fetches tags, reads the latest stable release's recorded cutoff (or uses the tag for older releases), associates every later `main` commit with GitHub pull requests, and presents the pull requests in chronological order. Prior release metadata commits are skipped.

Select the last pull request that should ship. Every non-release commit from the previous cutoff through that pull request is included. Later commits remain deferred to the next release. A pull request cannot be partially included, and commits cannot be removed from the middle of the range.

Commits without an associated pull request appear as standalone choices.

## Curate public notes

After selecting the code cutoff, choose which included changes should appear in public notes. Internal maintenance is excluded by default. Titles, categories, highlights, and breaking-change status can be edited before anything is written.

The generator writes:

- A new section at the top of `CHANGELOG.md`
- Curated GitHub release notes in `.github/release-notes.md`
- Release metadata in `.release.toml`
- Every included pull request author and commit co-author
- First-time contributor markers from GitHub pull request metadata

Existing changelog sections are preserved byte for byte. Future releases only insert one new section after the changelog introduction.

## Versions and channels

The tool suggests a version bump from the selected changes. Maintainers can choose patch, feature, major, or an explicit version.

Supported channels:

| Channel | Example | Registry behavior |
|---------|---------|-------------------|
| Stable | `1.11.0` | Updates the latest GitHub, npm, and Docker tags |
| Release candidate | `1.11.0-rc.1` | Published as a prerelease and does not replace latest |
| Beta | `1.11.0-beta.1` | Published as a prerelease and does not replace latest |
| Alpha | `1.11.0-alpha.1` | Published as a prerelease and does not replace latest |

The same version is written to the CLI, server, web, and Pi extension packages.

## Release branch and pull request

The tool creates `release/vX.Y.Z` from the selected cutoff, not from the latest `main`. Its release commit may change only:

- Package version files
- Python lockfiles
- `CHANGELOG.md`
- `.release.toml`
- `.github/release-notes.md`

The branch is pushed to the maintainer fork and a fully populated pull request is opened. Because the branch starts at the selected cutoff, GitHub may show that it is behind `main`; do not update it. Merge it with squash, rebase, or the squash-configured merge queue.

## Pipeline

After the merge, the workflow finds the release commit anywhere in the pushed `main` range, resolves its associated merged pull request, and fetches that pull request's exact head. Every build checks out that validated head, so later code already on `main` cannot enter the release even though `main` remains linear.

Release tags can therefore point to a detached release head rather than an ancestor of `main`. The next release reads the prior manifest's recorded cutoff and discovers later changes from that point; tags created before release manifests existed fall back to their tagged commit.

Before approval, the workflow builds:

- CLI binaries for Linux, macOS, and Windows
- Multi-architecture API and web container digests
- The server deployment archive

The production environment approval then unlocks the release tag and registry publishing. After approval, the workflow:

1. Creates or verifies the annotated tag
2. Publishes the Python package
3. Publishes the Pi extension with the correct npm channel
4. Publishes Docker manifests without moving `latest` for prereleases
5. Publishes the Helm chart
6. Creates a draft GitHub release with curated notes and checksums
7. Verifies every expected asset before publishing the GitHub release
8. Verifies PyPI, npm, Docker, Helm, and the installed CLI

Build failures occur before tag creation. A failed workflow can be resumed with GitHub's failed-job rerun. Manual workflow dispatch accepts the validated release preparation commit SHA for recovery.

## Safety checks

The local tool and workflow reject releases when:

- The working tree is dirty
- Local `main` differs from `upstream/main`
- The previous release's recorded cutoff (or a pre-manifest tag) is missing or not an ancestor of the selected cutoff
- The cutoff is not an ancestor of `main`
- A pull request is split across noncontiguous commits
- The release commit contains application code
- Package versions disagree
- Release notes omit the contributor section
- The changelog already contains the target version
- The tag points to another commit
- The automatic target is not the exact head of one associated merged release pull request

If local preparation fails after creating its worktree, the worktree is preserved under `.worktrees/` for inspection and recovery.

## Immutable package recovery

Published PyPI and npm versions cannot be replaced. If publication is partially successful, rerun only failed jobs after confirming the successful registry entries. If released code is wrong, publish a corrected patch and deprecate the bad npm version where appropriate. Restore Docker deployment tags only after documenting the incident.

## Configuration

The tool defaults to `upstream` for the organization repository and `origin` for the maintainer fork. The `upstream` and `fork` command options can select different remote names when the canonical clone is `origin` or a fork uses another name.
