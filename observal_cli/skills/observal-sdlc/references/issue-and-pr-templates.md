<!-- SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Issue and PR templates

How to file issues and how to fill every field of the pull request template.
Fields marked required must be non-empty; the PR is closed if template sections
are left as placeholders.

## Issue templates

Blank issues are enabled, and there is a contact link to GitHub Discussions for
questions, support, and early feature ideas. Two structured forms exist:

### Bug (`🐞 Bug`, label `Needs Triage`, type `Bug`)

- **Checked for duplicates?** (required) confirm the issue is not a duplicate.
- **Steps to reproduce** (required) what you did that triggered the bug.
- **Expected behaviour** (required) what happened vs. what should have happened.
- **Support bundle** attach the `.tar.gz` produced by the `observal support bundle` command; you can review it first with `observal support inspect`.
- **Anything else?** optional extra context.

### Feature Request (`💡 Feature Request`, title prefix `[FEATURE] `, label `accepted`)

- **Problem** (required) the problem you are solving; describe the problem, not just the solution.
- **Solution** (required) what you want to happen.
- **Alternatives** other approaches you considered.
- **Additional context** screenshots or extra detail.

Consider starting in GitHub Discussions or `#feature-requests` on Discord before
filing a formal request for larger features.

## Pull request template

Fill each section. Reproduce the structure below and replace the guidance text.

- **Purpose / Description** describe the problem or feature and the motivation.
- **Fixes** link the issue, e.g. `Fixes #123`. If there is genuinely no tracking issue, say so explicitly rather than leaving the placeholder.
- **Approach** how the change addresses the problem.
- **How Has This Been Tested?** the tests you ran and how to reproduce them, plus relevant test configuration.
- **Learning (optional)** research notes, links to posts, patterns, or libraries used.
- **Checklist** tick each item honestly:
  - Descriptive commit message with a short title (first line, max 50 chars).
  - Code commented, particularly in hard-to-understand areas.
  - You performed a self-review.
  - UI changes include screenshots of all affected screens (especially new or changed strings).
- **Licenses** uncomment and fill the table only if the PR introduces new external resources (libraries, icons): one row per resource with Library, Description, and License.
- **AI Assistance** state whether generative AI tooling co-authored the PR, name the tool, and confirm the generated code was manually reviewed and tested. This is required, not optional, and it must be truthful (see the AI policy in [conventions-and-standards.md](conventions-and-standards.md)).

### Filled example

```text
## Purpose / Description
Adds a `skill submit` command so contributors can publish skills from the CLI.

## Fixes
* Fixes #142

## Approach
New Typer command wraps the registry submit API and validates SKILL.md
frontmatter before the network call.

## How Has This Been Tested?
`make test` (unit) plus a manual submit against a local stack via
`make rebuild-fast`. Steps to reproduce in the PR discussion.

## Checklist
- [x] Descriptive commit message with a short title (max 50 chars)
- [x] Commented hard-to-understand areas
- [x] Performed a self-review
- [ ] UI changes: screenshots (n/a, CLI only)

## AI Assistance
- [x] Yes (tool): Kiro CLI, used interactively under maintainer direction
- [x] The generated code was manually reviewed and tested
```
