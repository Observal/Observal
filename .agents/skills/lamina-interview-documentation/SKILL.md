---
name: lamina-interview-documentation
description: "Walkthrough evidence — structured capture from browser/repo sessions. Not human session notes."
metadata:
  lamina:
    id: interview-documentation
    problems:
      - "document walkthrough"
      - "capture actor walk evidence"
    related:
      - lamina-field-research
      - lamina-orchestrator/patterns/visual-walkthrough
---
# Walkthrough Evidence (agent-native)

Document **observable evidence** from live product sessions — structured for verify and findings.

## Capture format

Per step:
- `screen_id` / URL
- Action taken (click, fill, navigate)
- Expected vs observed (contract ref)
- Screenshot or DOM snapshot ref (walkthrough pack)
- Blocker flag if actor cannot proceed

Persona perspective walks output structured JSON per `persona-panel-spawn.md`.

## Anti-patterns

- **Narrative notes** — prose without reproducible steps
- **Paraphrased feelings** — replace with blocked operation + screen

## Related

- [Visual Walkthrough](../lamina-orchestrator/patterns/visual-walkthrough.md)
- [Field Research](../lamina-field-research/SKILL.md)
