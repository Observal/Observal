---
name: lamina-quantitative-validation
description: "Metrics discipline — use only real user-provided data; suggest what to measure post-launch. No invented A/B results."
metadata:
  lamina:
    id: quantitative-validation
    problems:
      - "what to measure"
      - "metrics without fabrication"
    related:
      - lamina-feedback-loops
      - lamina-verify
---
# Metrics Discipline (agent-native)

Agents **do not invent** analytics. Quantitative validation is **advisory** until real data exists.

## Allowed

- Suggest metrics tied to workflows (completion rate, error rate, time-to-ticket)
- Define success signals in `decisions.md` for post-launch
- Incorporate user-provided dashboards or experiment results into scope

## Forbidden

- Fabricated A/B outcomes
- Made-up conversion rates
- Claims of statistical significance without user data

## Verify tie-in

Use **actor walk success/fail counts** as qualitative proxy pre-launch — not population statistics.

## Related

- [Feedback Loops](../lamina-feedback-loops/SKILL.md)
