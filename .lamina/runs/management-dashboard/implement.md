# Implement — management-dashboard (post-verify)

This verify run audited the shipped Executive Dashboard. Application edits happen in a later coding turn from `fix.md`. This ship pack summarizes the frozen graph slice and proof obligations.

## Target
`/dashboard` Executive Dashboard (Admin).

## Critical promises
1. **admin-only-access** — Only admin-tier actors load exec metrics; denials are explicit.
2. **honest-empty-setup** — Missing data routes to reachable setup surfaces.
3. **recoverable-load-failures** — Failures are accurate and retryable.

## Authoritative surfaces / APIs
- UI: `web/src/pages/admin/dashboard/**`, route `_authed/_admin/dashboard`
- Guard: `web/src/routes/_authed/_admin.tsx`, sidebar Admin nav
- API: `/api/v1/exec/*` in `observal-server/api/routes/exec_dashboard.py`

## Do not expand scope
Registry home, CLI ops, harness adapters, and live insight LLM quality are out of this fix slice unless required to close a finding above.

## Fix order
Follow `.lamina/runs/management-dashboard/fix.md` high → medium → low (includes Cmd+K role filtering after error taxonomy).

## Proof / recheck after fixes
- Reviewer deep-link denied at UI boundary
- Admin loads Adoption with empty and error branches
- Cost baselines save/recover
- Departments empty points to Users
- Export accessible without `alert()`
- Re-run `/lamina-verify` on the management dashboard after changes
