# Web Frontend

Next.js 16 / React 19 / TypeScript 6 / Tailwind CSS 4 / Playwright 1.59

## Stack

- **Framework:** Next.js 16 with `output: "standalone"` for Docker
- **UI:** shadcn/ui (`src/components/ui/`), Recharts 3 for charts, TanStack Query for data fetching, TanStack Table for sortable/filterable tables
- **Design system:** OKLCH color space with 5 themes (light, dark, midnight, forest, sunset). Typography: Archivo (display), Albert Sans (body), JetBrains Mono (code). 4pt spacing scale. Defined in `globals.css`.
- **API proxy:** Next.js rewrites (`/api/v1/*` → backend). Backend URL via `NEXT_PUBLIC_API_URL` (defaults `http://localhost:8000`).
- **Auth:** API key + user role in localStorage. Client-side guards (AuthGuard, AdminGuard, RoleGuard), not middleware.
- **GraphQL:** `/api/v1/graphql` is the read layer for telemetry. REST for everything else. WebSocket subscriptions via `src/lib/graphql-ws.ts`.

## Route groups

```
src/app/
├── (auth)/login/               # Login + first-run admin init
├── (registry)/                 # Public agent browser (requires auth)
│   ├── page.tsx                #   Registry home (search, trending, top rated)
│   ├── agents/page.tsx         #   Agent list with search + filters
│   ├── agents/[id]/page.tsx    #   Agent detail with pull command box
│   ├── agents/builder/page.tsx #   Agent builder (two-column, component selector, YAML preview)
│   ├── agents/leaderboard/page.tsx #   Agent leaderboard rankings
│   ├── components/page.tsx     #   Tabbed component browser (MCPs, skills, hooks, prompts, sandboxes)
│   └── components/[id]/page.tsx#   Component detail
├── (admin)/                    # Admin dashboard (requires admin role)
│   ├── dashboard/page.tsx      #   Overview stats, recent agents, latest traces
│   ├── review/page.tsx         #   Review queue with detail sheet
│   ├── users/page.tsx          #   User management
│   ├── settings/page.tsx       #   Enterprise settings
│   ├── eval/page.tsx           #   Eval overview with agent scores
│   ├── eval/[agentId]/page.tsx #   Eval detail (aggregate chart, dimension radar, penalty accordion)
│   └── errors/page.tsx         #   Error log viewer
└── (user)/                     # User-scoped views (requires auth)
    ├── traces/page.tsx         #   User trace list with filtering
    └── traces/[id]/page.tsx    #   Trace detail (resizable span tree + JSON viewer)
```

## Component directories

```
src/components/
├── builder/       # Agent builder (preview panel, sortable component list, validation panel)
├── dashboard/     # Stat cards, trend charts, bar lists, heatmap, time range select
├── layouts/       # AuthGuard, AdminGuard, RoleGuard, DashboardShell, PageHeader
├── nav/           # RegistrySidebar, CommandMenu (Cmd+K), NavUser, GitHubStarBanner
├── registry/      # AgentCard, AgentEditForm, ComponentCard, ComponentEditForm, PullCommand, InstallDialog, StatusBadge, SubmitComponentDialog, RegistryTable, RegistryDetail, ReviewForm, MetricsPanel, FeedbackList, IdeBadges, VersionBumpDialog, VersionDropdown
├── review/        # ReviewDetailSheet, ValidationBadges
├── shared/        # SkeletonLayouts, ErrorState, EmptyState
├── traces/        # TraceList, TraceDetail, SpanTree
└── ui/            # shadcn/ui primitives (27 components)
```

## Key files

- `src/lib/api.ts` : Typed fetch wrapper; all REST + GraphQL calls; auth via localStorage
- `src/lib/types.ts` : Shared TypeScript interfaces for all API responses
- `src/lib/graphql-ws.ts` : GraphQL WebSocket subscription client
- `src/lib/ide-features.ts` : IDE feature detection utilities
- `src/lib/query-client.ts` : TanStack Query client configuration
- `src/lib/utils.ts` : Shared utility functions
- `src/lib/export.ts` : Data export utilities
- `src/hooks/use-api.ts` : TanStack Query hooks for every endpoint (queries + mutations)
- `src/hooks/use-auth.ts` : Auth guard hook (checks API key exists)
- `src/hooks/use-admin-guard.ts` : Admin role check hook
- `src/hooks/use-role-guard.ts` : Generic role check hook
- `src/hooks/use-deployment-config.ts` : Deployment config fetcher (endpoint discovery)
- `src/hooks/use-mobile.ts` : Mobile viewport detection
- `src/components/registry/component-edit-form.tsx` : Unified component editor (hook, skill, prompt, MCP, sandbox type-specific forms)
- `src/components/registry/version-bump-dialog.tsx` : Semver version bump dialog for publishing new versions
- `src/components/registry/version-dropdown.tsx` : Version selector dropdown with status badges
- `src/components/registry/agent-edit-form.tsx` : Agent editor with goal template and component selector
- `next.config.ts` : API rewrites, standalone output
- `playwright.config.ts` : E2E test config (Chromium, port 3000)

## Commands

```bash
pnpm dev          # dev server on :3000
pnpm build        # production build
pnpm lint         # ESLint
pnpm test:e2e     # Playwright e2e tests (requires running API + Docker stack)
# E2E specs live in web/e2e/*.spec.ts (16 spec files)
```

## Enterprise feature gating

There is NO `web/ee/` directory. Enterprise frontend code lives here in `web/src/`, gated server-side via `useDeploymentConfig()`. This follows the Langfuse/PostHog/Infisical pattern — the `ee/` boundary is backend-only.

**Current enterprise conditionals:**
- `src/app/(auth)/login/page.tsx` — SSO button shown when `ssoEnabled`
- `src/app/(admin)/settings/page.tsx` — enterprise settings section shown when `deploymentMode === "enterprise"`
- `src/hooks/use-deployment-config.ts` — fetches `{ deploymentMode, ssoEnabled, samlEnabled }` from `/api/v1/config/public`

**Pattern for new enterprise pages:** Add regular pages in `src/app/(admin)/` that check deployment mode and show an upgrade prompt when not enterprise. Don't duplicate pages or create separate directories.

**Future resource-based access control:** API will include `user_access_level` on response objects (PostHog annotation pattern). Frontend reads the annotation — no client-side policy engine needed.

## Conventions

- No Tailwind config file — Tailwind CSS 4 uses `globals.css` for all design tokens
- Theme switching via `src/components/ui/theme-switcher.tsx`
- All API response types are centralized in `src/lib/types.ts` — don't define inline types for API data
- Use TanStack Query hooks from `src/hooks/use-api.ts` for data fetching — don't call `fetch` directly in components
- Semantic color tokens: background, foreground, card, border, primary, secondary, accent, destructive, success, warning, info
