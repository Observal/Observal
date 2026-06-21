<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Web Frontend

Next.js 16 / React 19 / TypeScript 6 / Tailwind CSS 4 / Playwright 1.59

## How users interact with it

The web UI is one of three ways to interact with Observal (alongside the CLI and the bundled observal skill). It covers:

- **Browsing and installing agents** from the registry
- **Viewing session traces** (conversation replay, span tree, token counts)
- **Admin operations** (review queue, user management, insights, audit logs)
- **Agent building** (drag-and-drop component assembly with live YAML preview)

## Stack decisions

| Concern | Choice | Why |
|---------|--------|-----|
| Framework | Next.js 16 (`output: "standalone"`) | Docker-friendly, RSC-ready |
| UI primitives | shadcn/ui | Composable, accessible, themeable |
| Data fetching | TanStack Query via `use-api.ts` | Caching, deduplication, mutations |
| Tables | TanStack Table | Sort, filter, pagination built-in |
| Charts | Recharts 3 | Simple, works with OKLCH tokens |
| Auth | sessionStorage (API key + role) | Not localStorage. Guards are client-side. |
| API proxy | Next.js rewrites (`/api/v1/*` → backend) | Single origin, no CORS in prod |
| Fonts | Local files only | No Google Fonts CDN calls |
| Design tokens | OKLCH in `globals.css` | Perceptually uniform, 5 themes |
| IDE list | Server-fetched (`/api/v1/config/harnesses`) | Never hardcoded in frontend |

## Design system

OKLCH color space with semantic tokens: `background`, `foreground`, `card`, `border`, `primary`, `secondary`, `accent`, `destructive`, `success`, `warning`, `info`.

5 themes: light, dark, midnight, forest, sunset. Defined in `globals.css` via CSS custom properties. Switched by `theme-switcher.tsx`.

Typography: Archivo (display/headings), Albert Sans (body), JetBrains Mono (code). 4pt spacing scale. Motion tokens for animations.

No Tailwind config file: Tailwind CSS 4 reads tokens directly from `globals.css`.

## Route groups

```
src/app/
├── (auth)/                         # Unauthenticated
│   ├── login/page.tsx              #   Login + first-run admin init
│   └── device/page.tsx             #   Device authorization (OAuth device flow)
├── (registry)/                     # Authenticated, any role
│   ├── page.tsx                    #   Registry home (search, trending, top rated)
│   ├── agents/page.tsx             #   Agent list with search + filters
│   ├── agents/[id]/page.tsx        #   Agent detail with pull command box
│   ├── agents/builder/page.tsx     #   Agent builder (component selector, YAML preview)
│   ├── components/page.tsx         #   Tabbed component browser (all 5 types)
│   ├── components/[id]/page.tsx    #   Component detail
│   └── leaderboard/page.tsx        #   Agent leaderboard rankings
├── (admin)/                        # Admin role required
│   ├── dashboard/page.tsx          #   Overview stats, recent agents, latest traces
│   ├── review/page.tsx             #   Review queue with detail sheet
│   ├── insights/page.tsx           #   Insight reports (license-gated)
│   ├── insights/[reportId]/page.tsx#   Individual insight report
│   ├── users/page.tsx              #   User management
│   ├── settings/page.tsx           #   Settings (sections gated by feature flags)
│   ├── sso/page.tsx                #   SSO / SAML / OIDC config (license-gated)
│   ├── audit-log/page.tsx          #   Audit log with parameterized search
│   ├── security-events/page.tsx    #   Security event log
│   ├── diagnostics/page.tsx        #   System diagnostics
│   └── errors/page.tsx             #   Error log (stubbed, pending rework)
└── (user)/                         # Authenticated, own data
    ├── traces/page.tsx             #   Session trace list
    ├── traces/[id]/page.tsx        #   Trace detail (span tree + JSON viewer)
    └── account/page.tsx            #   Account settings
```

## Key directories

```
src/components/
├── builder/       # model-picker, preview-panel, sortable-component-list, validation-panel
├── dashboard/     # Stat cards, trend charts, bar lists, heatmap, time range select
├── layouts/       # AuthGuard, AdminGuard, RoleGuard, DashboardShell, PageHeader
├── nav/           # RegistrySidebar, CommandMenu (Cmd+K), NavUser, GitHubStarBanner
├── registry/      # AgentCard, AgentEditForm, ComponentCard, ComponentEditForm, PullCommand,
│                  # InstallDialog, StatusBadge, SubmitComponentDialog, RegistryTable,
│                  # RegistryDetail, ReviewForm, FeedbackList, IdeBadges, VersionBumpDialog,
│                  # VersionDropdown
├── review/        # ReviewDetailSheet, ValidationBadges
├── shared/        # SkeletonLayouts, ErrorState, EmptyState
├── traces/        # TraceList, TraceDetail, SpanTree
└── ui/            # shadcn/ui primitives
```

## Key files

- `src/lib/api.ts` : Typed fetch wrapper, auth via sessionStorage
- `src/lib/types.ts` : ALL shared TypeScript interfaces for API responses
- `src/lib/graphql-ws.ts` : GraphQL WebSocket subscription client
- `src/lib/ide-features.ts` : IDE capability detection
- `src/lib/query-client.ts` : TanStack Query client config
- `src/hooks/use-api.ts` : TanStack Query hooks for every endpoint
- `src/hooks/use-auth.ts` : Auth guard (checks sessionStorage)
- `src/hooks/use-deployment-config.ts` : Feature flags and license status
- `src/hooks/use-ides.ts` : IDE list from server

## Coding patterns

**Data fetching:** Always use hooks from `use-api.ts`. Never call `fetch` directly in components. The hooks handle caching, error states, loading states, and refetching.

**Types:** All API response types live in `src/lib/types.ts`. Do not define inline types for data that comes from the API. If a new endpoint is added, add its types there.

**Feature gating:** Enterprise features are gated server-side. The API returns 403 for unlicensed features. The frontend reads `useDeploymentConfig()` for display decisions (show/hide sections, upgrade prompts) but never trusts the client to enforce access.

**IDE list:** Fetched from `/api/v1/config/harnesses` via `useIdes()`. Never hardcode IDE names or capabilities in the frontend. The server is the single source of truth.

**Auth state:** Stored in sessionStorage (not localStorage). `useAuth()` hook checks for presence. Three guard components: `AuthGuard` (any logged-in user), `AdminGuard` (admin role), `RoleGuard` (configurable role check).

**Theming:** Use semantic tokens (`var(--primary)`, `var(--destructive)`, etc.). Never use raw color values. All 5 themes are defined in one `globals.css` block.

## Commands

```bash
pnpm dev          # dev server on :3000
pnpm build        # production build
pnpm lint         # ESLint
pnpm e2e          # Playwright (requires running Docker stack)
pnpm e2e:kiro     # Kiro-specific e2e tests
pnpm e2e:ui       # Playwright UI mode
```

E2E specs live in `tests/e2e/*.spec.ts` (19 files, separate pnpm workspace at repo root).

## Enterprise in the frontend

There is NO `web/ee/` directory. Enterprise pages live in `src/app/(admin)/` alongside core pages. They call license-gated API endpoints. If the feature isn't licensed, the server returns 403 and the frontend shows an upgrade prompt.

This follows the Langfuse/PostHog pattern: the `ee/` boundary is backend-only. The frontend is AGPL and gates features server-side.
