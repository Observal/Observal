---
name: lamina-design-process
description: "Agent-native design loop — domain contract, external build, verify, iterate. Not human workshop ceremony."
metadata:
  lamina:
    id: design-process
    problems:
      - "design workflow for agents"
      - "iterate after verify"
    related:
      - lamina-design
      - lamina-verify
      - lamina-evolutionary-rules
---
# Design Process (agent-native)

The loop for coding agents: **design contract → implement (external) → verify → fix.md → re-verify**.

## Loop

1. `/lamina-init` — domain charter
2. `/lamina-design` — `run.json` + `implement.md` at `ready_to_build`
3. External implementation (any stack)
4. `/lamina-verify` — actor walks, invariants, a11y → `findings[]` + `fix.md`
5. External fix — coding agent implements product fixes from `fix.md`
6. Re-verify — `/lamina-verify` on updated build
7. Contract gaps → `/lamina-design` delta (prompts in `fix.md`); re-verify

## Anti-patterns

- **Workshop theater** — sticky notes, double-diamond ceremonies without contracts
- **Skip verify** — shipping without actor walks against live product
- **One-shot design** — no iteration after build

## Related

- [Design](../lamina-design/SKILL.md)
- [Verify](../lamina-verify/SKILL.md)
