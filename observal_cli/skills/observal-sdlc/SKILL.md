---
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-License-Identifier: Apache-2.0
name: observal-sdlc
command: observal
description: "Guides a contributor or coding agent through Observal's software development lifecycle: forking, branch naming, running the stack, conventional commits, SPDX headers, tests, filling the issue and pull request templates, the AI policy, the CLA, and code-review merge gates. Use when preparing, committing, or submitting any change (code, docs, or a registry component) to the Observal repository."
version: 1.0.0
owner: observal
---

# Contributing to Observal (SDLC)

You are shepherding a change into the Observal repository. Follow the process
exactly: reviewers close pull requests that skip these steps.

## Execution contract

1. **Fork is mandatory.** Contribute from a fork; there is no direct push access to `Observal/Observal`. Open pull requests from `your-fork:branch` against `Observal:main`.
2. **Never commit to `main`.** Always work on a topic branch. Rebase on `upstream/main` before opening the pull request.
3. **One concern per pull request.** Keep it small and focused. Split unrelated changes.
4. **Fill the pull request template completely.** Pull requests with unfilled or placeholder sections are closed without review.
5. **Every source file needs SPDX headers**, and every user-facing change follows Conventional Commits. CI blocks merges that miss either.
6. **Tests and linters must pass locally** (`make format`, `make lint`, `make test`) before you push.
7. **Disclose AI assistance and keep a human accountable.** Interactive, human-directed AI tooling is welcome; fully autonomous, unreviewed submissions are prohibited and closed on sight (see the AI Policy).
8. **Sign the CLA** when the bot prompts you on your first pull request.
9. Do not fabricate an issue number, a test result, or a passing check. Report real status only.

## Choose the workflow

| User intent | Read |
| --- | --- |
| Set up the fork, run the stack, branch, rebase, push, open the PR, claim an issue | [Contribution workflow](references/contribution-workflow.md) |
| File a bug or feature issue, or fill each field of the PR template | [Issue and PR templates](references/issue-and-pr-templates.md) |
| Get commits, SPDX headers, changelog, tests, code style, review gates, AI policy, and CLA right | [Conventions and standards](references/conventions-and-standards.md) |

Read only the reference you need, and read it completely before acting.

## Golden path

```bash
# 1. Fork on GitHub, then clone your fork and wire the upstream remote
git clone https://github.com/YOUR-USERNAME/Observal.git
cd Observal
git remote add upstream https://github.com/Observal/Observal.git

# 2. Branch from an up-to-date main (never work on main itself)
git fetch upstream
git switch -c feature/short-topic upstream/main

# 3. Make the change, install hooks, format, lint, and test
make hooks
make format
make lint
make test

# 4. Commit with a Conventional Commit subject (<= 50 chars, imperative, no period)
git add -A
git commit -m "feat(cli): add skill submit command"

# 5. Rebase on latest upstream, then push to YOUR fork
git fetch upstream && git rebase upstream/main
git push -u origin feature/short-topic
```

Then open a pull request on GitHub from `your-fork:feature/short-topic` into
`Observal:main`, fill every section of the template, add a `[Unreleased]`
changelog entry if the change is user-facing, sign the CLA, and respond to
review promptly.

## Completion

Report: the branch name, that the PR targets `Observal:main` from a fork, that
the template is fully filled, the local `make lint`/`make test` result, whether
a changelog entry was needed, the CLA status, and any reviewer or CI gate still
outstanding.
