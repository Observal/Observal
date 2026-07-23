# Design completion response

Only respond after `run.json` validates at `ready_to_build` and generated `run.md` plus `implement.md` exist.

Include:

- Product stage and critical promise.
- Consequential decisions or remaining non-blocking assumptions.
- Graph validation result.
- Paths to `run.json`, `run.md`, and `implement.md`.
- Next action: implement the generated contract, then run `/lamina-verify`.
