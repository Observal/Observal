<!-- SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Conventions and standards

The rules CI and reviewers enforce. Getting these right is what separates a
mergeable PR from a closed one.

## Commit messages (Conventional Commits)

Format: `type(scope): summary`. Subject in imperative mood, no trailing period.
The PR template asks for a title `<= 50` chars; CONTRIBUTING allows `<= 72`.
Keep it as short as the 50-char target when you can.

Types seen in the history: `feat`, `fix`, `docs`, `refactor`, `chore`, `ci`.
Append `!` to mark a breaking change. Real examples from merged PRs:

```
feat(web): revamp registry home
feat(cli)!: add help and error contracts
fix(security): harden diagnostics and CodeQL
refactor(cli): standardize table and JSON output modes
ci: target canonical Codecov project
chore(release): v1.12.1
docs: update contributing guide
```

## SPDX headers

Every source file needs an SPDX copyright line and license identifier. The
pre-commit hook adds them automatically; CI blocks merge if any file is missing
them. Comment syntax by file type:

```python
# SPDX-FileCopyrightText: 2026 Your Name <your@email.com>
# SPDX-License-Identifier: Apache-2.0
```

- TypeScript / JS: `// SPDX-...`
- Markdown / HTML: `<!-- SPDX-... -->`
- In a `SKILL.md`, place the SPDX lines as `#` comments inside the YAML frontmatter (between the `---` fences), matching the other bundled skills.

## Changelog

Add an entry under the `[Unreleased]` heading in `CHANGELOG.md` for any
user-facing change, grouped under `### Features`, `### Fixes`, etc., linking the
PR number. Release commits (`chore(release): vX.Y.Z`) roll these into a version.

## Code style

```bash
make hooks     # install pre-commit hooks first
make format    # ruff (Python) + TypeScript formatting
make lint      # ruff, hadolint (Dockerfiles), and other linters
```

## Testing

```bash
make test      # quick
make test-v    # verbose
```

All tests must pass before submitting, and every feature or bug fix ships with
tests. Tests mock external services (no Docker needed). New Python tests follow
the Testing Guide (`docs/testing/Testing_Guide.md`): keep them hermetic, assert
behavior over implementation details, use small local setup helpers, and never
touch real user configuration.

## Code review and merge gates

Every PR is evaluated under the Code Review Standard (`docs/code-review.md`),
which defines reviewer responsibilities, required approvals, review freshness,
merge gates, and the conditions that require changes or rejection. Keep PRs
small and single-purpose to move through review quickly. Rebase on
`upstream/main` before opening and when asked.

## AI policy (read before submitting)

Observal welcomes interactive, human-directed AI coding tools (Claude Code, Pi,
Cursor, Copilot, and similar). The accountable human must direct the work,
review the complete change, be able to explain it, and authorize publication.

Prohibited: fully autonomous agents that make material implementation choices
and submit code without meaningful human authorship (the concern is CLA
support, license-chain certainty, and training-data provenance, not tool
capability). PRs showing obvious signs of unreviewed AI output are closed
without review. Always disclose AI usage in the PR template's AI Assistance
section.

## CLA

The CLA-assistant bot prompts you to sign the Observal CLA on your first PR. You
sign once. For corporate contributions, contact the maintainer listed in
`CONTRIBUTING.md`.

## License

All code is licensed under Apache-2.0.
