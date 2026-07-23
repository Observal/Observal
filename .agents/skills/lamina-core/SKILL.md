---
name: lamina-core
description: "Lamina Problem Router — product design at the intersection of UX, product rules, and systems thinking."
---

# Lamina Core — Problem Router

Load one capability skill per problem.

## Entry points

| Command | Use when |
|---------|----------|
| `/lamina` | Auto-route or single-topic answer |
| `/lamina-init` | Bootstrap domain charter |
| `/lamina-design` | Design how the product works → `ready_to_build` |
| `/lamina-verify` | Post-build or brownfield verification |

**Guardrail:** `.lamina/` writes only; never app source. See [guardrails.md](guardrails.md).

## Systems thinking (spine)

| Problem signal | Skill |
|----------------|-------|
| Entities, relationships, purpose | [system-structure](../lamina-system-structure/SKILL.md) |
| Feedback, delays, oscillation | [feedback-loops](../lamina-feedback-loops/SKILL.md) |
| Fixes keep failing, structural traps | [system-traps](../lamina-system-traps/SKILL.md) |
| Where to intervene (rules vs UI) | [leverage-points](../lamina-leverage-points/SKILL.md) |
| Impossible states, business rules | [invariants](../lamina-invariants/SKILL.md) |
| Feature reachability, unmet prerequisites, degraded modes | [dependencies](../lamina-dependencies/SKILL.md) — **first-class** |
| Domain boundaries, hide complexity | [modularity-boundaries](../lamina-modularity-boundaries/SKILL.md) |
| What users see when (stale data) | [consistency-guarantees](../lamina-consistency-guarantees/SKILL.md) |
| Double-submit, concurrent edits | [idempotency-concurrency](../lamina-idempotency-concurrency/SKILL.md) |
| Name trade-offs before mechanisms | [tradeoffs](../lamina-tradeoffs/SKILL.md) |
| Multi-actor views stay consistent | [multi-view-integrity](../lamina-multi-view-integrity/SKILL.md) |
| Evolving rules safely | [evolutionary-rules](../lamina-evolutionary-rules/SKILL.md) |
| Notifications, downstream updates | [side-effects](../lamina-side-effects/SKILL.md) |
| Dates, deadlines, expiry, recurrence, timezones | [time-semantics](../lamina-time-semantics/SKILL.md) |

## UX and product expression

| Problem signal | Skill |
|----------------|-------|
| Bootstrap context | [business-context](../lamina-business-context/SKILL.md) |
| Inclusive design | [accessibility](../lamina-accessibility/SKILL.md) |
| Copy, labels, errors | [content-design](../lamina-content-design/SKILL.md) |
| Prioritize, resolve conflicts | [decision-making](../lamina-decision-making/SKILL.md) |
| Affordances, signifiers | [discoverability](../lamina-discoverability/SKILL.md) |
| Domain-empty screens | [empty-states](../lamina-empty-states/SKILL.md) |
| Violation recovery UX | [error-handling](../lamina-error-handling/SKILL.md) |
| Permission/conflict scenarios | [edge-cases](../lamina-edge-cases/SKILL.md) |
| Unreachable or silently broken prerequisites | [dependencies](../lamina-dependencies/SKILL.md) |
| Async feedback, status | [feedback-and-status](../lamina-feedback-and-status/SKILL.md) |
| User journeys over state | [flow-design](../lamina-flow-design/SKILL.md) |
| Forms under rules | [forms](../lamina-forms/SKILL.md) |
| Local date/time input | [time-semantics](../lamina-time-semantics/SKILL.md) |
| Entity organization | [information-architecture](../lamina-information-architecture/SKILL.md) |
| Wayfinding | [navigation](../lamina-navigation/SKILL.md) |
| First-run paths | [onboarding](../lamina-onboarding/SKILL.md) |
| UI reflects domain truth | [product-behavior](../lamina-product-behavior/SKILL.md) |
| Operations actors perform | [task-analysis](../lamina-task-analysis/SKILL.md) |
| Actors, roles, permissions | [user-modeling](../lamina-user-modeling/SKILL.md) |

## Agent simulation (replaces human research)

Human labs, interviews, and workshop ceremony are reframed as **contract + live-product simulation**.

| Problem signal | Skill |
|----------------|-------|
| Design→build→verify loop | [design-process](../lamina-design-process/SKILL.md) |
| Scope the design target | [problem-framing](../lamina-problem-framing/SKILL.md) |
| Map ask → workflows | [feature-discovery](../lamina-feature-discovery/SKILL.md) |
| What evidence vs assumption | [research-scoping](../lamina-research-scoping/SKILL.md) |
| Plan verify actor walks | [research-planning](../lamina-research-planning/SKILL.md) |
| Merge walk results | [research-synthesis](../lamina-research-synthesis/SKILL.md) |
| Report verify findings | [research-communication](../lamina-research-communication/SKILL.md) |
| Actor-walk scripts | [interview-design](../lamina-interview-design/SKILL.md) |
| Walkthrough evidence | [interview-documentation](../lamina-interview-documentation/SKILL.md) |
| Repo + live UI grounding | [field-research](../lamina-field-research/SKILL.md) |
| Simulated usability (verify) | [usability-evaluation](../lamina-usability-evaluation/SKILL.md) |
| Real metrics only | [quantitative-validation](../lamina-quantitative-validation/SKILL.md) |
| Conflicting actor goals | [stakeholder-alignment](../lamina-stakeholder-alignment/SKILL.md) |
| User-cited references | [competitive-analysis](../lamina-competitive-analysis/SKILL.md) |
| Workflow priority | [feature-prioritization](../lamina-feature-prioritization/SKILL.md) |
| Group permissions / shared state | [persuasion-and-groups](../lamina-persuasion-and-groups/SKILL.md) |
| Parallel expert lenses | [heuristic-review](../lamina-heuristic-review/SKILL.md) |
| Complexity budget / disclosure | [platform-posture](../lamina-platform-posture/SKILL.md), [progressive-disclosure](../lamina-progressive-disclosure/SKILL.md) |
| Payment / sensitive action honesty | [trust](../lamina-trust/SKILL.md) |
| Testable acceptance criteria | [requirements-definition](../lamina-requirements-definition/SKILL.md) |

## Supporting files

- [guardrails.md](guardrails.md)
- [artifacts.md](../lamina-orchestrator/artifacts.md)
- [lamina-orchestrator](../lamina-orchestrator/SKILL.md)
