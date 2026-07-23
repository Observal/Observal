---
name: lamina-feedback-and-status
description: "System state visibility in contracts — modeless feedback, progress, and async status. Use when actors can't tell what happened after actions."
metadata:
  lamina:
    id: feedback-and-status
    problems:
      - "users unsure if action worked"
      - "opaque system state changes"
      - "async operation status"
    related:
      - lamina-discoverability
      - lamina-error-handling
      - lamina-consistency-guarantees
    tags:
      - audit-default
---
# Feedback and Status (agent-native)

Every mutating operation declares **what the actor sees during and after** — in workflow steps and `scenarios[]`.

## Contract encoding

Per workflow step:
- `feedback`: immediate | progress | async_poll | silent_ok
- `visible_state`: what changes on screen (entity state, badge, banner)
- Async: `status: processing` scenario until terminal state

**Modeless feedback** preferred over modals for routine status.

## Frameworks

- **Visibility of system state**: actor always knows where they are in multi-step flows.
- **Forcing functions**: only for safety-critical irreversible ops — document in scenario.
- **Feedforward**: preview consequence before commit (destructive ops).

## Design checklists

1. No dialog reports normal completion.
2. Disabled controls explain why (link to scenario or inline hint).
3. Progress for ops > ~1s perceived wait.
4. Optimistic UI only when `consistency-guarantees` allow + rollback scenario exists.
5. Group related status in same screen region.

## Verify checks

- Actor walk: each mutating step produces expected visible feedback.
- Async probe: refresh during processing — stale state handled per invariant.
- Double-click submit — idempotency feedback (`idempotency-concurrency`).

## Anti-patterns

- Async silence — upload with no progress.
- Disabled with no explanation.
- "Are you sure?" without true irreversibility.
- Modal blocking batch flow for recoverable status.

## Related

- [Discoverability](../lamina-discoverability/SKILL.md)
- [Consistency Guarantees](../lamina-consistency-guarantees/SKILL.md)
- [Error Handling](../lamina-error-handling/SKILL.md)
