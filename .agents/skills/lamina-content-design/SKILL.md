---
name: lamina-content-design
description: "Copy and labels in contracts — scan-first labels, error text, and empty-state messaging. Use when screen copy blocks actor walks."
metadata:
  lamina:
    id: content-design
    problems:
      - "label ambiguity"
      - "unclear error copy"
      - "content-heavy screens"
    related:
      - lamina-navigation
      - lamina-discoverability
      - lamina-product-behavior
    tags:
      - audit-default
---
# Content Design (agent-native)

Specify **user-visible text** in `surfaces[]` — labels, headings, errors, empty states — so implementers and verify subagents share one source of truth.

## Contract encoding

Per screen:
- `title`, `primary_action` label
- `empty_state` copy when `scenarios` include `collection_empty`
- `error_messages` keyed by scenario id
- Navigation labels consistent with `workflows` operation names

**Concise copy**: every word earns its place; no happy talk on task screens.

## Frameworks

- **Scan-first**: headings, bullets, one primary CTA visible without reading paragraphs.
- **Satisficing**: first visible option on primary path should be correct.
- **Mindless choices**: mutually exclusive nav labels — depth beats ambiguous breadth.
- **Eliminate instructions**: if copy explains the UI, fix structure (`discoverability`).

## Design checklists

1. Page/screen title matches link that leads there.
2. Error copy: what happened → why → what to do next.
3. Labels use actor vocabulary from `entities[]`, not internal jargon.
4. Home/landing answers: what site, what can I do, why here, why trust — if applicable.
5. Halve marketing copy on task screens.

## Verify checks

- Actor walk: simulated actor finds primary action without re-reading labels.
- Walkthrough: link text ≠ page title mismatches → finding.
- a11y: link purpose clear out of context.

## Anti-patterns

- Welcome paragraphs users skip.
- "Click here" or jargon labels.
- Instructions compensating for bad layout.
- Clever headings that fail actor-walk goal completion.

## Related

- [Navigation](../lamina-navigation/SKILL.md)
- [Discoverability](../lamina-discoverability/SKILL.md)
- [Empty States](../lamina-empty-states/SKILL.md)
