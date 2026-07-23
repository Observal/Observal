---
name: lamina-controls-and-menus
description: "Actions and reversibility in contracts — primary/destructive actions, undo policy, confirmations. Use when destructive ops lack scenarios."
metadata:
  lamina:
    id: controls-and-menus
    problems:
      - "destructive action UX"
      - "undo and reversible actions"
      - "command placement"
    related:
      - lamina-forms
      - lamina-error-handling
      - lamina-platform-posture
      - lamina-progressive-disclosure
    tags:
      - interaction
---
# Controls and Actions (agent-native)

Specify **action semantics** in screen and workflow contracts — destructive, reversible, confirmation policy — not menu widget styling.

## Contract encoding

Per action on `surfaces[]`:
- `id`, `label`, `destructive: true|false`
- `reversible: true|false` → if true, confirmation usually unnecessary
- `confirmation_required` only when undo impossible + scenario documents
- `undo_scope`: step | session | none

Working-set actions on primary toolbar area in screen spec; full catalog in nav/menus.

## Frameworks

- **Ask forgiveness, not permission**: undo replaces confirm dialogs for recoverable ops.
- **Rich modeless feedback**: status in view, not modal for normalcy.
- **Preview/compare**: before irreversible-feeling changes — note in workflow step.

## Design checklists

1. Destructive ops have `scenarios[]` + recovery or undo policy.
2. Daily working-set actions ≤1-2 clicks from working screen.
3. Confirm only when invariant violation risk and undo absent.
4. Selection + manipulation pattern documented for sovereign apps.
5. Platform conventions noted in `implement.md` (web vs desktop) — Lamina stays unopinionated on library.

## Verify checks

- Actor walk: destructive op matches contract confirmation/undo behavior.
- Accidental click recovery — undo or cancel path exists per contract.

## Anti-patterns

- Confirm dialog for undoable delete.
- Modal error for recoverable validation.
- All actions equal weight on crowded screen spec.
- Hidden working-set functions three levels deep.

## Related

- [Error Handling](../lamina-error-handling/SKILL.md)
- [Forms](../lamina-forms/SKILL.md)
- [Platform Posture](../lamina-platform-posture/SKILL.md)
- [Progressive Disclosure](../lamina-progressive-disclosure/SKILL.md)
