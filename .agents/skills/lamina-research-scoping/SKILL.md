---
name: lamina-research-scoping
description: "Evidence scoping — what grounding is needed (repo, walkthrough, user input) vs assumption. Not human study scope."
metadata:
  lamina:
    id: research-scoping
    problems:
      - "what evidence do we need"
      - "assumption vs verified"
    related:
      - lamina-research-planning
      - lamina-field-research
---
# Evidence Scoping (agent-native)

Before design or verify, list **what evidence exists** and what must be captured.

| Evidence | Source |
|----------|--------|
| Domain rules | User input, `business-context.md` |
| Existing UI | Repo `surfaces[].source`, walkthrough pack |
| Actor behavior | Verify actor walks on live product |
| Metrics | User-provided only — never invented |

Label each design claim: **verified**, **assumption**, or **to-verify**.

## Anti-patterns

- **Exhaustive research scope** — delaying contract without blocking gaps
- **Invented analytics** — fake A/B or usage data

## Related

- [Live Grounding](../lamina-field-research/SKILL.md)
