# Verification report — management-dashboard

## Grounding mode
**static_source** (primary). Host `localhost:8080` responded, but no authenticated admin session was available for a live walkthrough. Evidence is from `web/src/pages/admin/dashboard/**`, `web/src/routes/_authed/_admin*.tsx`, `web/src/components/nav/registry-sidebar.tsx`, and `observal-server/api/routes/exec_dashboard.py`.

## Target
Executive / management dashboard at `/dashboard` — six tabs (AI Adoption, Cost Intelligence, Investments, AI Insights, Departments, Velocity) behind Admin navigation.

## Critical promises vs evidence

| Promise | Verdict | Notes |
|---|---|---|
| admin-only-access | **Fail** | API + nav require admin; `_admin` layout RoleGuard is `reviewer`, so deep-links mount the shell then fail loads as “connection” errors |
| honest-empty-setup | **Partial** | Cost baselines form and Insights generate CTA are strong; Departments empty misroutes to Settings; onboarding correctly cites Users |
| recoverable-load-failures | **Fail** | Tabs show generic connection copy; no in-panel Retry; Refresh skips `ai-insights` query |

## Persona panel
Mandatory packs run for `persona.agent-consumer`, `persona.platform-admin`, `persona.stack-operator` via isolated reviewers. Structural/contradiction/missing_recovery items merged into `persona_findings[]` with `source: persona_hypothesis`. Preferential items remain labeled research hypotheses (not product requirements).

## Full-flow lenses applied
flow-design, heuristic-review, navigation, discoverability, forms, error-handling, content-design, accessibility, trust, feedback-and-status, decision-making — no lenses skipped.

## Prioritized product improvements
1. Align RoleGuard / nav / API admin boundary and permission copy
2. Error taxonomy + in-panel Retry
3. Filter Cmd+K navigate items by role (parity with sidebar)
4. Fix Departments empty-state routing
5. Accessible export without `alert()`
6. Tokenize raw hex chart colors
7. Canonical naming (contract)

## Follow-up evidence
[Explore management dashboard](25148ea8-69af-4118-801c-268aa1ba78ee) confirmed route/API map and surfaced the Cmd+K role-filter gap; e2e coverage for exec tabs remains thin (auth redirect + Kiro smoke only).

## Residual risk
Live permission and empty-data behavior not exercised in browser. ClickHouse-empty vs outage distinction inferred from UI branches only. Redis fail-closed symptoms on this surface remain unverified live.

## Artifacts
- `.lamina/runs/management-dashboard/run.json` (`status: complete`)
- `.lamina/runs/management-dashboard/run.md`
- `.lamina/runs/management-dashboard/report.md`
- `.lamina/runs/management-dashboard/fix.md`
- `.lamina/runs/management-dashboard/implement.md`
