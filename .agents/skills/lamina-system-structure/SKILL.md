---
name: lamina-system-structure
description: "Product system structure — entities, relationships, purpose, and quantities that change over time. Use when defining what exists in the product domain and how parts connect."
metadata:
  lamina:
    id: system-structure
    problems:
      - "domain entities and relationships"
      - "what objects exist in the product"
      - "system purpose and boundaries"
      - "quantities that accumulate or drain"
    related:
      - lamina-invariants
      - lamina-feedback-loops
      - lamina-dependencies
      - lamina-information-architecture
      - lamina-user-modeling
    tags:
      - design-default
---
# System Structure

Map the product as a system in `run.json` `domain` — elements, interconnections, purpose — before screens or external implementation.

## Verify

Re-read `domain` after external build: actor walks and invariant probes must reference the same entities and relationships; drift → `findings[]`.

## Decision frameworks

- **Three-part system definition**: Elements + interconnections + purpose. A random list of screens is not a system; exams, venues, tickets, and the rules linking them are.
  - When to use: Scoping any feature or domain area.
  - How: Name entities, how they affect each other, and the product outcome the system serves.

- **Stocks and flows (product quantities)**: Stocks are accumulations (tickets issued, seats remaining, unpaid fees). Flows are rates of change (registrations per day, cancellations).
  - When to use: Any persistent quantity users care about — inventory, capacity, status counts.
  - How: Identify stock, inflows, outflows; stocks change slowly and act as buffers and delays.

- **Purpose revealed by behavior**: Stated goals may differ from what the product actually optimizes. Design for the behavior you want, not the slogan.
  - When to use: Resolving conflicts between marketing copy and product rules.

- **Interconnections over parts**: Information links often matter more than physical data movement. Who knows what, when, drives behavior.
  - When to use: Multi-actor products (student, admin, exam cell).

## Checklists

1. List domain entities and relationships before screens.
2. For each entity, note ownership — who creates, updates, or deletes it.
3. Identify stocks users care about (tickets left, exam capacity).
4. Map inflows and outflows for each stock.
5. State the system's purpose in one sentence testable against workflows.
6. Distinguish real system from mere collection of unrelated features.

## Heuristics

- **Bathtub thinking**: Stocks integrate flows over time — users cannot expect instant results when a large stock must fill or drain.
- **Stocks as shock absorbers**: Large stocks relative to flows = stability; small stocks = volatility.
- **Both levers exist**: Raising a stock means increasing inflow OR decreasing outflow.

## Anti-patterns

- **Element obsession**: Listing screens or tables without interconnections.
- **Inflow-only thinking**: Ignoring that reducing outflow raises stocks as effectively as increasing inflow.
- **Ignoring stock inertia**: Expecting policy changes to show immediate results.
- **Open chain without feedback**: Some flows are linear, but most product behavior involves feedback.

## Examples

- **Exam hall tickets**: Entities — Student, Exam, Venue, HallTicket. Stock — tickets issued per exam session. Flows — registration (in), cancellation (out). Purpose — assign each student exactly one valid seat for each exam they take.

## Related capabilities

- [Dependencies](../lamina-dependencies/SKILL.md) — reachability between features and entity states
- [Invariants](../lamina-invariants/SKILL.md) — rules that must hold across entities
- [Feedback Loops](../lamina-feedback-loops/SKILL.md) — how quantities self-correct or amplify
- [Information Architecture](../lamina-information-architecture/SKILL.md) — organizing entities for findability
