<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Roadmap

This document describes what Observal intends to do (and not do) for at
least the next year. It is a living document, updated as priorities shift.

## Current focus (2026 Q3)

- **OpenSSF Scorecard hardening**: raise all checks to 10/10. Pinned
  dependencies, signed releases, token permissions, and fuzzing integration
  are in progress or planned.
- **Supply-chain maturity**: SBOM generation, VEX documents, build
  provenance attestation, and Renovate-driven digest pinning.
- **Harness coverage**: promote functional harnesses (Codex CLI, Copilot,
  Copilot CLI, OpenCode) to first-class with session parsers and hook specs.

## Planned (2026 Q4)

- **Insights engine v2**: richer agent performance reports with cross-agent
  benchmarking, trend analysis, and HTML export improvements.
- **Team workspaces**: full team-private visibility, membership roles, and
  team-scoped publishing already shipped, now focus on UX and bulk
  operations.
- **Self-hosting hardening**: Helm chart maturity, Terraform module coverage
  for AWS and GCP, and production deployment guides.

## Planned (2027 H1)

- **ClusterFuzzLite / OSS-Fuzz integration**: continuous fuzzing of session
  parsers, harness config generation, and auth token handling.
- **GraphQL telemetry layer**: expand the read-only GraphQL API with more
  subscription types and richer query filters.
- **Plugin SDK**: allow third-party harness adapters without forking the
  CLI.

## Not planned

- **Multi-tenant SaaS hosting**: Observal is self-hosted software. We do
  not plan to operate a hosted SaaS instance.
- **Agent execution**: Observal observes and configures agents, it does not
  run them. Agent execution is out of scope.
- **Non-AI-coding-agent use cases**: the platform is designed for AI coding
  agents. General-purpose LLM observability is not a goal.

## How to influence the roadmap

Open a GitHub issue with the `feature` label or start a discussion in
[GitHub Discussions](https://github.com/Observal/Observal/discussions).
Maintainers review proposals and update this document when priorities
shift.
