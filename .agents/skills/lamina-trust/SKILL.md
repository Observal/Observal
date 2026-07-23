---
name: lamina-trust
description: "Trust signals in contracts — transparency for payments, irreversible actions, and sensitive data. Use when actors hesitate on verify walks or scenarios lack honesty UX."
metadata:
  lamina:
    id: trust
    problems:
      - "payment and sensitive action anxiety"
      - "opaque fees or consequences"
      - "actors abandon before commit"
    related:
      - lamina-feedback-and-status
      - lamina-content-design
      - lamina-controls-and-menus
      - lamina-product-behavior
---
# Trust Signals (agent-native)

Trust is **observable honesty in product behavior** — specified in scenarios and screen copy, verified when simulated actors attempt high-stakes workflows.

## Contract encoding

For payment, PII, and irreversible operations:
- `surfaces[]`: show fees, consequences, and final state before commit
- `scenarios[]`: false success, hidden charges, unclear irreversibility → category `failure` or finding
- `workflows[]`: confirmation only when undo impossible (`controls-and-menus`)
- Side effects visible before actor commits (`side-effects`)

## Checklists

1. High-stakes step shows what changes in domain state (ticket issued, payment captured).
2. No success UI before authoritative state confirmed (`consistency-guarantees`).
3. Error and delay copy honest — no fake urgency.
4. Sensitive data: actor sees only what their role requires (`modularity-boundaries`).
5. Support/recovery path in scenario when trust-breaking failure occurs.
6. Consequential sign-in proves account control in the runnable current slice; a public email or client-selected role is not authentication.
7. Cookie-authenticated state changes declare `HttpOnly`, appropriate `SameSite`/`Secure` posture, and CSRF token or trusted-origin validation. Development fallbacks are visibly limited and production fails closed without required identity configuration.

## Verify checks

- Actor walk: payment/download/regenerate flows — actor reports hesitation or surprise → finding.
- Probe partial failure (payment ok, ticket pending) — UI must not claim complete success.
- Compare marketing copy in repo vs contract promises if user cites mismatch.

## Anti-patterns

- Success toast before durable state.
- Hidden fees revealed after commit.
- Dark patterns (fake scarcity, trick confirm).
- Security theater copy without matching behavior in scenarios.

## Related

- [Feedback And Status](../lamina-feedback-and-status/SKILL.md)
- [Consistency Guarantees](../lamina-consistency-guarantees/SKILL.md)
- [Content Design](../lamina-content-design/SKILL.md)
