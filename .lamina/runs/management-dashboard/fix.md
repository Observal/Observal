# Fix brief — management-dashboard

Product and contract findings from the Executive Dashboard audit, priority order. Implement in application source in a later fix turn; this file is the brief only.

## FIND-role-guard-mismatch — product — high

- **Graph:** `workflow.denied-or-mismatched-access`, `invariant.admin-api-boundary`, `operation.open-dashboard`, `surface.executive-dashboard`
- **Evidence:** `@web/src/routes/_authed/_admin.tsx` uses `RoleGuard minRole="reviewer"` for all admin routes including `/dashboard`. `@web/src/components/nav/registry-sidebar.tsx` lists Dashboard with `minRole: "admin"`. `@observal-server/api/routes/exec_dashboard.py` uses `require_role(UserRole.admin)` on exec endpoints.
- **Acceptance:**
  - Non-admin users cannot mount the Executive Dashboard UI
  - Denied users see an explicit permission message (not a connection failure)
  - Sidebar visibility matches route guard and API role
- **Recheck:** Reviewer deep-link to `/dashboard`; admin happy path; Review route still reachable for reviewers

## FIND-error-taxonomy-retry — product — high

- **Graph:** `operation.load-exec-metrics`, `scenario.metrics-load-fail`, `workflow.view-adoption-overview`, `surface.executive-dashboard`
- **Evidence:** Tab `isError` branches (e.g. `@web/src/pages/admin/dashboard/components/adoption-tab.tsx`) show “Failed to load … Check your connection and try again” with no Retry. Header Refresh in `@web/src/pages/admin/dashboard/index.tsx` invalidates `["exec"]` but excludes `ai-insights`.
- **Acceptance:**
  - 403 shows permission denial copy
  - 5xx/network shows retryable error with Retry calling refetch
  - Successful empty aggregates still use empty-state copy
- **Recheck:** All six tabs; Insights generate path; Refresh vs Retry interaction

## FIND-command-menu-role-leak — product — medium

- **Graph:** `workflow.denied-or-mismatched-access`, `invariant.admin-api-boundary`, `operation.open-dashboard`, `surface.executive-dashboard`
- **Evidence:** `@web/src/components/nav/command-menu.tsx` renders every `allNavItems` entry with no `hasMinRole` filter; sidebar filters Admin items by role. Confirmed by [Explore management dashboard](25148ea8-69af-4118-801c-268aa1ba78ee).
- **Acceptance:**
  - Cmd+K Navigate group only lists routes the current role can access
  - Reviewer/user is not offered `/dashboard` or Settings when unauthorized
  - Deep-link denial remains explicit if navigated another way
- **Recheck:** Reviewer Cmd+K; admin Cmd+K; Settings still `super_admin`-only

## FIND-departments-empty-misroute — product — medium

- **Graph:** `scenario.no-departments`, `surface.executive-dashboard`
- **Evidence:** `@web/src/pages/admin/dashboard/components/departments-tab.tsx` empty copy cites Settings; onboarding in `index.tsx` correctly cites Users; Settings nav requires `super_admin`.
- **Acceptance:**
  - Empty departments copy names Users (and optional SSO) as the assignment path
  - Does not send admins to Settings unless that is the correct reachable surface
- **Recheck:** Onboarding wizard wording stays consistent with Departments empty

## FIND-export-a11y-trust — product — medium

- **Graph:** `surface.executive-dashboard`, `workflow.view-adoption-overview`
- **Evidence:** `ExportDropdown` in `@web/src/pages/admin/dashboard/index.tsx` scrapes DOM tables and uses `alert()` when none exist; menu lacks accessible naming/state.
- **Acceptance:**
  - No `window.alert` for empty export
  - Export control is keyboard accessible with announced menu state
  - Empty export uses inline feedback on the active tab
- **Recheck:** Departments/Velocity/Investments table tabs; print path

## FIND-token-colors — product — low

- **Graph:** `surface.executive-dashboard`
- **Evidence:** Raw hex in `@web/src/pages/admin/dashboard/components/cost-tab.tsx` and `investments-tab.tsx` vs web AGENTS.md OKLCH token rule
- **Acceptance:** Charts/badges use semantic CSS tokens only
- **Recheck:** Light/dark themes on Cost and Investments

## FIND-contract-naming — contract — low

- **Graph:** `surface.executive-dashboard`
- **Evidence:** UI title “Executive Dashboard”, nav “Dashboard”, audit brief “management dashboard”
- **Acceptance:** One agreed label across nav, page header, docs, and future run targets
- **Recheck:** Breadcrumbs and e2e selectors that assume `/dashboard`
