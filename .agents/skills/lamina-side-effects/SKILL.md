---
name: lamina-side-effects
description: "Downstream effects of state changes — notifications, updates to related entities, and cross-actor handoffs. Use when one operation must trigger updates beyond the primary screen."
metadata:
  lamina:
    id: side-effects
    problems:
      - "notifications on state change"
      - "cascading updates across entities"
      - "handoff to another actor or system"
      - "what else must update when X changes"
    related:
      - lamina-multi-view-integrity
      - lamina-consistency-guarantees
      - lamina-flow-design
      - lamina-feedback-and-status
    tags:
      - design-default
---
# Side Effects

State changes rarely stop at one screen. Document who and what else must update when domain state changes — in product terms, not integration diagrams.

## Decision frameworks

- **Primary effect**: The intended outcome of the operation (ticket issued).
- **Side effects**: Required follow-ups (notify student; update roster; invalidate old ticket; log audit entry for exam cell).
  - When to use: Any mutating operation on shared or lifecycle entities.
  - How: List in workflow step or `domain` entity notes; scenarios when side effect fails.

- **Notification as product rule**: Who must be told, what channel, what content, when — not which email provider.
  - When to use: Venue change, payment failure, approval granted/denied.

- **Delivery as an operational boundary**: Keep the authoritative in-product state separate from an append-only delivery-attempt lifecycle (`queued`, `delivered`, `delivery_failed`, retry/acknowledgement when applicable).
  - Current slice: provide a runnable local capture/adapter and a concrete provider interface, configuration and health seam. Do not call local capture “sent.” Production mode fails closed when required provider configuration is absent.
  - Recovery: preserve the original recipient binding for audit, route future attempts according to the declared current recipient policy, bound retries, and keep the urgent/in-product state visible when delivery fails.

- **Compensating action**: What happens if side effect fails (payment succeeded but ticket not created → show support path, do not show success).

## Checklists

1. For each mutating operation, list primary effect and all required side effects.
2. Define actor responsible for each side effect (system vs human role).
3. Write scenarios for partial failure (payment ok, ticket not ready).
4. Ensure UI reflects in-flight side effects (pending, not false success).
5. Map side effects to `workflows` steps and `scenarios` recovery UX.
6. Name the independent runner, cadence/tolerance, idempotency key, retry/rebinding policy, provider health proof, and visible delivery state for time-sensitive delivery.

## Anti-patterns

- **Fire-and-forget**: State change without notifying affected actors.
- **Success before side effects complete**: User believes done while roster still stale.
- **Unowned handoff**: No actor responsible when payment gateway and ticket system disagree.
- **Adapter theater**: A log statement or in-memory array is described as external delivery, with no runnable invocation path or provider seam.
- **Delivery erases truth**: The product remains non-urgent because a notification failed.

## Examples

- **Venue change**: Primary — exam.venue updated. Side effects — void outstanding tickets or flag for regen; notify students; refresh invigilator roster; audit log entry. Scenarios — student opens old PDF after change.

## Related capabilities

- [Multi-View Integrity](../lamina-multi-view-integrity/SKILL.md)
- [Consistency Guarantees](../lamina-consistency-guarantees/SKILL.md)
- [Flow Design](../lamina-flow-design/SKILL.md)
- [Feedback and Status](../lamina-feedback-and-status/SKILL.md)
