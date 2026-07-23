---
name: lamina-interview-design
description: "Actor-walk script design — probe operations, goals, and failure modes per simulated actor. Not human moderator craft."
metadata:
  lamina:
    id: interview-design
    problems:
      - "design actor walk script"
      - "what should simulated user try"
    related:
      - lamina-usability-evaluation
      - lamina-user-modeling
      - lamina-orchestrator/patterns/persona-panel
---
# Actor-Walk Script Design (agent-native)

Design **what each simulated actor attempts** on the live product during verify.

## Script template

Per actor:
- **Goal** — outcome from persona (e.g. download ticket before exam)
- **Starting context** — role, permissions, data state
- **Happy path** — operations in order
- **Stress probes** — forbidden actions, race timing, error recovery
- **Success criteria** — observable UI/state + invariant holds

Spawn via persona-panel pattern; one subagent per actor.

## Anti-patterns

- **Open-ended interview** — "tell me how you feel" without operations
- **Leading questions** — scripting answers instead of observing behavior

## Related

- [User Modeling](../lamina-user-modeling/SKILL.md)
- [Persona Panel](../lamina-orchestrator/patterns/persona-panel.md)
