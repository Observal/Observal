---
lamina:
  maturity: brownfield
  platform: [web, cli]
  last_updated: 2026-07-23
---

# Business context

## Problem statement
**Answer:** Organizations produce internal AI coding components (agents, MCP servers, skills, hooks, prompts, sandboxes) faster than teams can find, reuse, or improve them. Components live in siloed repos with weak documentation, so developers rebuild similar packages; publishers lack a usage feedback loop, and AI failures are silent (hallucinations / subtle wrongness) rather than actionable. Observal is the control plane and system of record: a governed registry for discovery/install plus session-backed insights and traces so shared AI tooling improves from real use.
**Confidence:** high
**Evidence:** @README.md (What is Observal / Why teams use Observal); @AGENTS.md (product definition)
**Skill:** lamina-problem-framing, lamina-feature-discovery

## Business goals
**Answer:** Become the trusted internal distribution and observability layer for AI coding agents: one place to publish, review, install, and learn from agents across supported harnesses. Near-term success looks like teams preferring Observal-installed agents over ad-hoc local copies, admins running a reviewable registry, and session/insight data informing which shared components to keep or fix. Open-source adoption (self-hosted stacks, CLI installs) and multi-harness coverage remain strategic levers.
**Confidence:** medium
**Evidence:** @README.md (Why teams use Observal; Open-source features); assumption — needs validation for org-specific 6–12 month OKRs
**Skill:** lamina-stakeholder-alignment

## Success metrics
**Answer:** Leading signals (product-observable, not invented baselines): registry install/pull volume and unique installers; share of approved vs pending submissions cleared through review; harness coverage of active installs (first-class vs stub); session ingest/reconcile health (delivery success, parse coverage); insight report usage for agent/component improvement. Supporting ops metrics: time-to-first `observal pull` after server deploy, doctor/patch success across harnesses. Exact numeric targets and baselines are unknown without stakeholder input.
**Confidence:** low
**Evidence:** @README.md (registry, insights, session replay); @AGENTS.md (telemetry pipeline); assumption — needs validation for baselines and targets
**Skill:** lamina-stakeholder-alignment, lamina-research-scoping

## Scope
**Answer:** In scope: self-hosted server (API, web UI, Postgres, ClickHouse, Redis, workers), CLI (`observal`) for auth/registry/agent lifecycle/doctor/reconcile, multi-harness config generation and scanning, agent as primary package (five component types), admin review/governance, session ingest + insights, bundled Observal skills for in-harness driving. Explicitly out / deferred for this context: building third-party harness products themselves; replacing general APM/LLM observability platforms; inventing OTEL/MCP telemetry wrappers (telemetry is session hooks + reconcile only); first-class session parsers/hooks for stub harnesses until promoted.
**Confidence:** high
**Evidence:** @README.md; @AGENTS.md (architecture, harness tiers, no OTEL policy); @docs/adding-a-harness.md
**Skill:** lamina-feature-prioritization, lamina-stakeholder-alignment

## Users & market
**Answer:** Primary market is tech-forward organizations that already create internal AI coding components and need discovery + governance + usage learning—not consumers shopping public agent marketplaces alone. Primary users: developers/AI coding users who discover and pull agents into their harness. Secondary: component/agent authors who publish and need adoption signal; platform admins who review, approve, and operate policy; operators who deploy and maintain the stack. Not primarily serving: non-technical end users without a coding harness; teams seeking only cloud SaaS without self-host option (product is self-host oriented today). Alternatives/inertia: siloed Git repos, per-harness manual config, ad-hoc MCP/skill installs, anecdote-driven iteration.
**Confidence:** medium
**Evidence:** @README.md (problem framing, surfaces, governance); @AGENTS.md (CLI / web / skill interaction modes)
**Skill:** lamina-user-modeling, lamina-competitive-analysis

## Product posture
**Answer:** Multi-surface control plane: sovereign web UI for browse/build/review/insights/ops; sovereign CLI for install, registry CRUD, doctor, reconcile, and server ops; transient-but-authoritative in-harness Observal skill that drives CLI from the coding agent. Density is high for power users (admins, authors, operators) and task-focused for pull/install. Platform complexity budget: harness adapters and feature flags keep unsupported operations safe stubs; first-class harnesses get hooks + session parsers + e2e. Trust posture: API-key auth, review gates with owner-install fallback, audit logging, SSRF guards on outbound network.
**Confidence:** high
**Evidence:** @README.md (Quick Start, registry, review); @AGENTS.md (auth, adapter pattern, owner fallback)
**Skill:** lamina-platform-posture

## Constraints
**Answer:** Technical: Docker Compose self-host stack; Python 3.11+ CLI; Next.js web; Postgres + ClickHouse + Redis; strict harness adapter pattern (no harness if/elif chains); ClickHouse migrations separate from Alembic; Redis fail-closed for auth. Product policy: no OTEL/telemetry env wrappers on MCP; hard rewrite (no deprecation shims); canonical identity `namespace/slug`. Org/process: AI contribution policy (human authorship, explainable changes); Apache-2.0. Unknown without stakeholders: regulatory regimes (beyond shipped audit/SSO/SCIM mentions), budget, and forced single-harness mandates.
**Confidence:** high (technical/policy); low (regulatory/budget)
**Evidence:** @AGENTS.md; @README.md (open-source features); @AI_POLICY.md (referenced in AGENTS.md)
**Skill:** lamina-research-scoping

## Stakeholders
**Answer:** Product/engineering maintainers of Observal (architecture and harness support); org admins/reviewers who gate what is installable; developers and authors who create demand and supply for the registry; operators who must keep the stack healthy; harness ecosystems (Claude Code, Cursor, Kiro, Pi, etc.) as external platforms Observal must track. Conflicts to design for: author desire for fast publish vs admin desire for review; submitter access to own pending items vs preferred approved catalog; telemetry richness vs privacy/redaction expectations.
**Confidence:** medium
**Evidence:** @README.md (Review and Governance; owner workflows in AGENTS.md); assumption — needs validation for named org sponsors
**Skill:** lamina-stakeholder-alignment

## Risks & unknowns
**Answer:** If session capture quality or harness coverage lags, insights and traces lose trust and the feedback-loop promise fails. If review UX or install friction is high, shadow installs return. If identity/versioning (`namespace/slug`, versions) confuses users, registry trust erodes. Unknowns: which persona is truly primary in deploying orgs (developer vs platform team); monetization if any beyond open-source; retention and privacy expectations for session content; which stub harnesses must become first-class next. Assumptions that hurt in six months if wrong: that orgs will self-host; that session hooks remain the right telemetry path; that agents (not lone MCPs) stay the primary packaging unit.
**Confidence:** medium
**Evidence:** @AGENTS.md (harness tiers, telemetry pipeline); @README.md; assumption — needs validation
**Skill:** lamina-feature-discovery, lamina-research-scoping

## Research posture
**Answer:** Evaluative-first on brownfield surfaces (registry browse/install, agent builder, review queue, insights, session replay, CLI doctor/pull) with generative follow-ups only where goals/metrics/privacy remain unvalidated. Evidence sources: repo + docs + live product walkthroughs; do not invent analytics. Decisions that need evidence before major UX bets: primary installer path (CLI vs web vs in-harness skill), review queue priorities, and what insight facets drive real component changes.
**Confidence:** medium
**Evidence:** @README.md (UI screenshots of shipped surfaces); @docs/; lamina-research-scoping
**Skill:** lamina-research-scoping, lamina-problem-framing

## Triad check
**Answer:** Capability is strongest (registry, multi-harness config gen, ingest, insights, governance already shipped). Desirability is plausible from the stated dual problem (discoverability + feedback) but not user-validated here—medium. Viability (self-host ops burden, ClickHouse/session scale, harness churn, contributor policy) is the weakest pillar to watch: operators and harness promotion cost can outrun product surface polish.
**Confidence:** medium
**Evidence:** @README.md; @AGENTS.md; assumption — needs validation with operators and deploying teams
**Skill:** lamina-product-behavior

## Inferred context
Brownfield scan of public product docs and agent architecture notes. Shipped interaction modes: CLI, web UI, bundled Observal skill inside harnesses. Domain core entities: users/orgs, agents (bundling MCP/skill/hook/prompt/sandbox), versions, review decisions, sessions/events, insight reports. Telemetry path is session push hooks and `observal reconcile` → ingest → ClickHouse—not OTLP wrappers.
**Evidence:** @README.md, @AGENTS.md, @docs/self-hosting/, @docs/adding-a-harness.md
