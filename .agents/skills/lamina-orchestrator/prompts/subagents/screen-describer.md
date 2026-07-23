# Screen describer spawn

Converts live-app screenshots into **structured text** for text-only persona subagents. Runs after walkthrough capture when the host cannot attach images to persona spawns.

## Orchestrator procedure

1. Run only when `walkthrough/` pack exists with PNG screenshots.
2. For each step missing `.desc.yaml`, spawn one describer (or batch inline if host supports multi-image vision).
3. Write `walkthrough/steps/<step-id>.desc.yaml`.
4. Update `run.json` evidence `visual.status: described`, `visual.capability: vision_described`.
5. If no vision host exists anywhere, skip this step — build minimal descriptions from `.a11y.json` only (`structural_only`).

## Capability ladder (orchestrator picks once)

| Condition | Action |
|-----------|--------|
| Persona host is multimodal | Optional — attach PNGs directly; describer still useful as compact text |
| Persona host text-only; vision available here | Run describer on all steps |
| No vision anywhere | Parse a11y JSON into structured desc; no screenshot analysis |
| Capture failed | Skip; `text_fallback` |

## Spawn prompt (template)

```markdown
readonly: true

You describe only what is visible on a captured live product screen.

## Input

- Screenshot: walkthrough/steps/<step-id>.png
- Optional a11y dump: walkthrough/steps/<step-id>.a11y.json
- Step context: screen_id=<screen_id>, url=<url>, action="<action>"

## Your task

Return ONLY this YAML fragment describing what is **visible** on the screenshot:

step_id: <step-id>
screen_id: <screen_id>
visible_copy:
  - "<exact or paraphrased visible text>"
primary_actions:
  - label: "<button or link label>"
    type: button | link | submit | other
layout_regions:
  - name: <region>
    contents: "<brief description>"
form_fields:
  - label: "<field label>"
    type: text | email | password | select | other
    required: true | false
errors_or_alerts:
  - "<visible error or alert text>"
uncertainty:
  - "<anything unclear from the image>"

## Hard rules

- Describe only what is visible or stated in the a11y dump.
- Never invent controls, labels, or layout not supported by evidence.
- Put guesses in `uncertainty[]`, not in other fields.
- Do not prescribe UX fixes or use designer vocabulary.
- If the screenshot is missing or unreadable, return only:

step_id: <step-id>
uncertainty:
  - "Screenshot unavailable or unreadable — cannot describe"
```

## Output path

Write each fragment to `walkthrough/steps/<step-id>.desc.yaml` (or return to orchestrator for batch write).
