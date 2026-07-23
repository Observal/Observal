---
name: lamina-task-analysis
description: "Operations actors perform — map tasks to workflows and navigation. Use when workflows[] or IA don't match actor goals."
metadata:
  lamina:
    id: task-analysis
    problems:
      - "mapping actor operations"
      - "task navigation design"
      - "deal-breaker tasks"
    related:
      - lamina-flow-design
      - lamina-information-architecture
      - lamina-requirements-definition
---
# Task Analysis (agent-native)

Decompose actor goals into **operations** — verbs on domain entities — that become `workflows[]` steps and navigation structure.

## Procedure

1. From primary actor goals (`personas.json`), list operations: "download ticket", "assign venue".
2. Group operations into workflows by outcome, not by backend module.
3. Rank **deal-breaker** operations — if blocked, actor abandons product.
4. Map working-set (daily) operations to shortest nav path in screen specs.
5. Rare operations → progressive disclosure (`platform-posture`).

## Contract encoding

- `workflows[].steps` = ordered operations; use `requires` + `dependencies[]` for prerequisites
- `task-analysis` prose optional in `report.md` for complex domains
- Navigation labels = operation vocabulary, not org chart

## Design checklists

1. Nav structured by tasks, not implementation modules.
2. Index/wayfinding separated from work area on sovereign apps.
3. Key paths ≤ few steps for working-set tasks.
4. Edge tasks reachable but not prominent.
5. Each operation links to permission in `actors`.

## Verify checks

- Actor walk: deal-breaker operations completable on live product.
- Measure steps vs contract workflow length.

## Anti-patterns

- Org-chart or file-system navigation.
- Deep hierarchy for daily tasks.
- Operations in contract that no actor has permission to perform.

## Related

- [Flow Design](../lamina-flow-design/SKILL.md)
- [Requirements Definition](../lamina-requirements-definition/SKILL.md)
- [Navigation](../lamina-navigation/SKILL.md)
