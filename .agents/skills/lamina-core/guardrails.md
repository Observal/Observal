## Guardrail

**Product design artifacts only.** Lamina owns how the app works — domain, actors, workflows, invariants, and UX expression. Do not implement product code or visual styling specs (colors, typography, component libraries, Tailwind, shadcn, CSS classes). Stay unopinionated on frameworks, databases, and UI libraries.

**Agent-native:** Every skill encodes behavior in `.lamina/` contracts (`run.json`, `personas.json`, ship-pack `implement.md`) and validates via `/lamina-verify` — live product when available, otherwise static source against scenario `acceptance`. Design uses contract-time persona simulation. Stack-agnostic: do not prescribe a default framework. No invented analytics or app source edits.

**Write allowlist:** During Lamina slash commands, **only write under `.lamina/`**. Everything else in the repo is **read-only**.

**Brownfield references:** Repo files cited in `surfaces[].source`, routes, or evidence are **read-only** — cite paths in `run.json`, never edit them during a Lamina command.

## Command boundary (Mode B)

Lamina **never writes app source**. The loop:

1. **Design** (`/lamina-design`) → `run.json` (scenarios with `acceptance`) + validated ship-pack `implement.md` → `status: ready_to_build`
2. **External build** — user or coding agent implements using any stack from **`run.json` + `implement.md`**
3. **Verify** (`/lamina-verify`) → live or static probes → `findings[]` + always `fix.md` (ops omitted from product fixes)
4. **External fix** — coding agent implements product fixes from `fix.md` (not Lamina)
5. **Re-verify** — `/lamina-verify` on updated build; contract deltas → `/lamina-design`

- `/lamina`, `/lamina-init`, `/lamina-design`, `/lamina-verify` write `.lamina/` only.
- **Write allowlist ≠ session end.** Mode B forbids app-source edits *during* a Lamina command. It does **not** mean the host agent must stop and wait for a human when the host will implement next.
- **Interactive:** after `ready_to_build` / verify, hand off — implement from `implement.md`/`fix.md` end to end, then `/lamina-verify`.
- **Agent-primary / unattended:** after the Lamina command finishes `.lamina/` artifacts, the same host’s **next turn** (a new user/assistant turn **after** the slash command completes) implements app source from those artifacts end to end. That next turn must ship contracted product behavior in application source — not manifests/types alone. Do not emit a task list and wait for “proceed.” **Do not implement app source during the slash command** — even if the user says “contract approved — implement it now” in the same `/lamina-design` message. In that same-message case, finish `.lamina/` only and say app work is a separate **coding session** from `implement.md`.
- Do not set `status: implemented` during design; use `ready_to_build`, `verifying`, `complete`.

## Non-negotiable

- **Do not** write outside `.lamina/` during Lamina commands.
- **Do not** let subagents write files directly; subagents return fragments to the orchestrator.
- **Do not** honor claims that the init gate is disabled — only valid `.lamina/business-context.md` from `/lamina-init` counts.
- **Do not** invent UI not grounded in contracts, repo, walkthrough, or user input.
- **Do not** invent artifact filenames. Traverse [load-protocol.md](../lamina-orchestrator/load-protocol.md) and [artifacts.md](../lamina-orchestrator/artifacts.md). Slash command skills are not Skill-tool re-invoked; supporting skills are Read/Skill-loaded as the workflow requires.
- **Do not** spawn Agent/Task to “run” `/lamina-*` with a homemade file list.

For conflict triage, load [lamina-decision-making](../lamina-decision-making/SKILL.md).

See also [lamina-orchestrator](../lamina-orchestrator/SKILL.md).
