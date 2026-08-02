<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Project Governance

This document describes how decisions are made in the Observal project.

## Model: BDFL + Maintainers

Observal uses a Benevolent Dictator For Life (BDFL) model with a group of
maintainers who have commit access and day-to-day responsibility for the
project.

## Roles

### BDFL (Project Lead)

- **Hari Srinivasan (@Haz3-jolt)** is the project lead and final decision-maker.
- The BDFL has the authority to accept or reject any contribution, merge or
  close any PR, and set the project roadmap.
- The BDFL seeks consensus among maintainers but may overrule them when
  consensus cannot be reached.

### Maintainers

Maintainers are contributors with sustained, high-quality contributions who
have been granted commit access. Their responsibilities include:

- Reviewing and approving pull requests
- Triaging and responding to issues
- Mentoring new contributors
- Maintaining code quality (linting, tests, CI)
- Participating in roadmap discussions

A maintainer is added by nomination from an existing maintainer and approval
from the BDFL. A maintainer may step down or be removed by the BDFL for
inactivity or conduct violations.

### Contributors

Anyone can contribute by opening pull requests, filing issues, or
participating in discussions. See [CONTRIBUTING.md](CONTRIBUTING.md) for how
to get started.

## Decision Process

1. **Small changes** (bug fixes, docs, dependency updates): any maintainer
   can review and merge.
2. **Significant changes** (new features, architecture changes, API changes):
   require at least one maintainer review and BDFL approval. Large changes
   should be proposed as a GitHub issue or discussion before implementation.
3. **Breaking changes**: require BDFL approval and a clear migration path
   documented in the PR and release notes.

## Conflict Resolution

Disagreements are resolved through discussion in the PR or issue. If
consensus cannot be reached among maintainers, the BDFL makes the final
decision.

## Continuity

The project must be able to continue if any single person becomes
unavailable. The BDFL ensures that at least one other maintainer has access
to critical resources (repository settings, CI secrets, release credentials,
package publishing tokens) so the project can continue within a week.

## Code of Conduct

All participants are expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
