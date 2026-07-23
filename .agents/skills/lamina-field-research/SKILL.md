---
name: lamina-field-research
description: "Live product grounding — repo and browser observation of real behavior. Not ethnography logistics."
metadata:
  lamina:
    id: field-research
    problems:
      - "ground design in real product"
      - "observe live UI"
    related:
      - lamina-interview-documentation
      - lamina-research-scoping
      - lamina-orchestrator/patterns/visual-walkthrough
---
# Live Product Grounding (agent-native)

**Field** = the running product and its repo — not physical site visits.

## Sources

| Source | Use |
|--------|-----|
| Repo | Routes, components, `surfaces[].source` |
| `base_url` walkthrough | Real navigation, states, errors |
| User-provided captures | Screenshots, logs, support tickets |

Ground every `screen` and `operation` claim in evidence or mark **assumption**.

## When to run

- **Design** — map existing UI before extending contract
- **Verify** — compare live behavior to `run.json`

## Anti-patterns

- **Ethnography logistics** — travel, recruitment, consent forms
- **Design from memory** — screens not tied to repo or walkthrough

## Related

- [Evidence Scoping](../lamina-research-scoping/SKILL.md)
