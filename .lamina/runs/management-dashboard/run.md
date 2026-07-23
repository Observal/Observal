# management-dashboard

Stage: **shape** · Status: **complete** · Contract: **2.0**

## Intent

Audit the management dashboard for empty states, failure recovery, permission boundaries, and admin task success

**Outcome:** Platform admins can govern registry and ops from the management dashboard with clear empty/failure/permission states

## Critical promises

- **admin-only-access** [critical] — Only admin-tier actors can reach and load Executive Dashboard metrics; denied actors get an explicit permission outcome
- **honest-empty-setup** [critical] — When adoption/cost/department data is missing, the dashboard shows actionable empty or setup guidance that routes to reachable admin surfaces
- **recoverable-load-failures** [critical] — When exec metrics fail to load, admins see an accurate failure reason and a reachable recovery path

## Actors

- **platform-admin** [critical] — Govern org AI adoption, cost, and insights from the Executive Dashboard
- **reviewer** [supporting] — Review registry submissions without executive org analytics

## Entities and lifecycles

- **exec-dashboard-view** [critical] — loading → ready → empty-setup → error → denied
- **exec-config** [critical] — missing → configured

## Operations

- **open-dashboard** [critical] — Dashboard shell visible for permitted layout roles
- **load-exec-metrics** [critical] — KPI cards, charts, or empty guidance
- **configure-cost-baselines** [critical] — Cost Intelligence KPIs unlock
- **generate-ai-insights** [supporting] — Cached executive insight sections

## Workflows

- **view-adoption-overview** [critical] — operation.open-dashboard → operation.load-exec-metrics
- **setup-cost-intelligence** [critical] — operation.open-dashboard → operation.configure-cost-baselines → operation.load-exec-metrics
- **denied-or-mismatched-access** [critical] — operation.open-dashboard → operation.load-exec-metrics

## Rules and invariants

- **admin-api-boundary** [critical] — All /api/v1/exec/* handlers use Depends(require_role(UserRole.admin)); client UI must not present successful metrics to non-admins
- **empty-not-zero-lie** [critical] — Missing telemetry or departments must show empty/setup guidance rather than invented non-zero executive claims

## Dependencies

- **exec-api** [critical] — workflow.view-adoption-overview requires operation.load-exec-metrics; unmet: Queries enter isError; tabs show Failed to load … Check your connection
- **session-telemetry** [critical] — workflow.view-adoption-overview requires entity.exec-dashboard-view; unmet: Charts/lists show No … data yet empty copy; KPIs may be zeros

## Scenarios

- **reviewer-deep-link** [critical] — undefined: Layout may allow reviewer; Sidebar hides Dashboard for non-admin; Exec API returns 403 while UI says connection failure
- **no-departments** [critical] — undefined: Departments tab shows empty guidance; Copy may point to Settings though admin assignment lives under Users
- **metrics-load-fail** [critical] — undefined: Tab shows Failed to load … Check your connection; No in-panel Retry; page Refresh may recover
- **missing-baselines** [critical] — undefined: Cost tab shows baselines form instead of fabricated savings

## Executable proofs

- **proof-admin-access** [undefined] — workflow.denied-or-mismatched-access: isError connection copy rather than permission denial
- **proof-adoption-load** [undefined] — workflow.view-adoption-overview: KPI row or empty/error panel
- **proof-cost-setup** [undefined] — workflow.setup-cost-intelligence: Savings KPIs after configured=true

## Persona findings

- **pf-consumer-authority-mismatch** [contradiction] — Executive Dashboard access is gated at three incompatible tiers: layout reviewer, nav admin, API admin—producing mismatched permission outcomes.
- **pf-consumer-metrics-no-recovery** [missing_recovery] — Tab metric failures show generic connection copy with no retry action.
- **pf-consumer-empty-tier-split** [structural_defect] — Departments empty directs to Settings (super_admin) while Users is the admin path—authority-dishonest empty recovery.
- **pf-consumer-graph-gap** [research_hypothesis] — Primary consumer goals (registry install/diagnose) are outside this admin dashboard graph; panel inclusion reflects primary-persona selection not surface ownership.
- **pf-admin-guard-api-mismatch** [structural_defect] — Reviewer-scoped RoleGuard lets non-admins open /dashboard then fail API loads without an explicit permission denial.
- **pf-admin-no-retry** [missing_recovery] — Metrics error panels lack operation-scoped retry; recovery is only via page Refresh.
- **pf-admin-empty-settings** [contradiction] — Departments empty routes to Settings instead of Users, conflicting with honest-empty-setup.
- **pf-admin-export-audit** [structural_defect] — Export via DOM scrape + alert() sits outside auditable server-backed export boundaries.
- **pf-admin-setup-asymmetry** [research_hypothesis] — Cost baselines have a coherent setup path while other empty modules feel less guided.
- **pf-ops-boundary-mismatch** [structural_defect] — Layout vs API tier mismatch yields non-explicit permission outcomes on the surface operators may use to sanity-check the stack.
- **pf-ops-failure-taxonomy** [structural_defect] — Failures collapse 403/5xx/empty ClickHouse into connection blame, blocking accurate ops diagnosis.
- **pf-ops-empty-vs-outage** [contradiction] — Undifferentiated errors make empty telemetry indistinguishable from broken ingest.
- **pf-ops-no-panel-retry** [missing_recovery] — No in-panel retry on metrics fail.
- **pf-ops-refresh-excludes-insights** [structural_defect] — Refresh invalidation excludes ai-insights cache, so partial faults can persist.
- **pf-ops-redis-unsurfaced** [research_hypothesis] — Redis fail-closed auth symptoms may surface as dashboard access/load failures without naming the dependency.
