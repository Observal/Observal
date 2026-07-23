# Lamina artifacts

During Lamina slash commands, write only below `.lamina/`. Implementation and fix turns may write application source.

## Canonical paths

| Path | Purpose |
|---|---|
| `.lamina/business-context.md` | Product and business context |
| `.lamina/personas.json` | Evidence-grounded actors and provisional perspectives |
| `.lamina/decisions.md` | Cross-run decision history |
| `.lamina/runs/<run_id>/run.json` | Canonical Contract v2 proof-budgeted product graph |
| `.lamina/runs/<run_id>/run.md` | Generated readable graph |
| `.lamina/runs/<run_id>/implement.md` | Generated task-scoped implementation contract |
| `.lamina/runs/<run_id>/report.md` | Human-readable verification report |
| `.lamina/runs/<run_id>/fix.md` | Product and contract fixes |
| `.lamina/runs/<run_id>/walkthrough/` | Optional live-product evidence |

Never create alternative contract, handoff, blueprint, or edge-case files. `run.md` and `implement.md` are generated projections; edit `run.json`, then render again.

## Lifecycle

### Design

1. Create `run.json` at `status: draft` and choose `stage: spark | shape | harden`.
2. Declare the proof budget and build the minimum sufficient graph for the current iteration, including only the trusted service/control structure and proof environment required by its critical promises.
3. Classify assumptions and decision forks.
4. Derive distinct risks and conduct up to three materially different persona walks.
5. Compile executable `proofs[]` covering every critical promise, workflow, operation, invariant, dependency, and surface.
6. Validate with the `graph-tool.mjs` bundled in the loaded `lamina-orchestrator` skill.
7. Resolve validation failures, confirm the generated ship pack retains authority, lifecycle, enforcement, dependencies, surfaces, and proof obligations, set `status: ready_to_build`, validate again, then render.
8. Confirm `run.md` and `implement.md` exist before completing the command.

### Verify

1. Load a ready contract or create a brownfield verification graph.
2. Set `status: verifying`.
3. Compare live behavior or static source to critical promises, workflows, rules, and scenarios.
4. Write ticket-shaped `findings[]` with evidence and acceptance.
5. Write `report.md` and `fix.md`, set `status: complete`, and validate.

## Tooling

```text
node <skill>/lib/graph-tool.mjs create <run.json> id=<id> target=<target> problem=<problem> outcome=<outcome> users=<ids> stage=<stage>
node <skill>/lib/graph-tool.mjs derive <run.json> [--write]
node <skill>/lib/graph-tool.mjs validate <run.json>
node <skill>/lib/graph-tool.mjs render <run.json>
node <skill>/lib/graph-tool.mjs coverage <run.json>
node <skill>/lib/graph-tool.mjs scope <run.json> <typed-ref>...
```

Read [references/product-graph.md](references/product-graph.md) for graph depth and typed references. The JSON Schemas are `references/run.schema.json` and `references/personas.schema.json`.
