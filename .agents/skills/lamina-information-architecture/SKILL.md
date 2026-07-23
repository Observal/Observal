---
name: lamina-information-architecture
description: "Entity organization and retrieval — how actors find domain objects in screens and nav. Use when IA mirrors files or tables instead of tasks."
metadata:
  lamina:
    id: information-architecture
    problems:
      - "structuring domain objects in UI"
      - "findability of entities"
      - "IA for task-oriented products"
    related:
      - lamina-task-analysis
      - lamina-navigation
      - lamina-system-structure
---
# Information Architecture (agent-native)

Organize **`entities[]`** for actor retrieval — recency, search, hierarchy — not filesystem or schema shape.

## Contract encoding

- Entity list drives nav sections and `surfaces[]` groupings
- Retrieval patterns per entity type: list, search, timeline, facets — in screen spec
- `entities[].relationships` inform parent/child nav — not foreign keys in UI copy

## Frameworks

- **Unified object model**: actors manipulate domain objects (tickets, exams), not paths or tables.
- **Retrieval**: recency + search + visual browse — match how actors remember work.
- **Auto-persist**: no "save?" anxiety — session/history scenarios if undo needed.

## Design checklists

1. IA follows task analysis operations, not org chart.
2. Recent/frequent objects promoted on dashboard screen.
3. Search across entity attributes actors know (name, date) — not internal ids.
4. Deep hierarchy only for rare admin paths.
5. Entity rename in domain → nav label update in same contract pass.

## Verify checks

- Actor walk: find entity by primary retrieval path on live product.
- "Where did it go?" after create operation → finding if contract promised visibility.

## Anti-patterns

- Exposing file paths, table names, module ids to actors.
- Folder drilling as only retrieval path.
- IA copied from database ERD without task mapping.

## Related

- [System Structure](../lamina-system-structure/SKILL.md)
- [Navigation](../lamina-navigation/SKILL.md)
- [Task Analysis](../lamina-task-analysis/SKILL.md)
