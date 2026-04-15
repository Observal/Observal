# Observal Web UI Reference

> **WIP:** Current screenshots show pages without demo data (empty states). These will be replaced with richer captures once seed data is available. Some pages (agent detail, component detail, trace detail, eval detail, enterprise login) are still pending. If you are contributing screenshots, use the dev server with demo data and capture at 1280x800 viewport.

Complete reference for the Observal web frontend. The UI is a Next.js 16 app located in `web/`. It communicates with the FastAPI backend at `/api/v1/*` via server-side rewrites.

> **Maintaining this doc:** When adding or modifying pages, update the corresponding section below. Keep descriptions in sync with the actual components in `web/src/app/`.

---

## Page Map

```
/                         Registry home (public)
/agents                   Agent list with search, sort, grid/table toggle
/agents/:id               Agent detail -- overview, components, reviews, install, analytics
/agents/leaderboard       Full leaderboard with time-window tabs
/agents/builder           Agent composer form (auth required)
/components               Component list -- MCPs, Skills, Hooks, Prompts, Sandboxes
/components/:id           Component detail -- overview, reviews, add-to-agent
/login                    Multi-mode auth (login, register, API key, SSO, password reset)
/dashboard                Admin dashboard -- stats, recent agents, latest traces, top downloads
/traces                   Session list with search, sort, active/all tabs
/traces/:id               Session detail -- event tree, filters, session info
/errors                   Error event viewer with type filters and expandable details
/eval                     Agent eval overview -- cards per agent with grades
/eval/:agentId            Eval detail -- score chart, history table, dimensions, penalties
/review                   Review queue -- approve/reject submissions (grid or list view)
/users                    User management -- list users, change roles, create users
/settings                 System settings -- key-value config, system overview (super admin only)
```

---

## Authentication & Authorization

### Auth Methods

The login page (`/login`) supports five modes:

| Mode | Fields | Description |
|------|--------|-------------|
| **Login** | Email, password | Standard email + password sign-in |
| **Register** | Email, name, password | Self-registration (disabled in enterprise mode) |
| **API Key** | API key | Paste a pre-generated API key (disabled in enterprise mode) |
| **SSO** | -- | OAuth/OIDC redirect via "Sign in with SSO" button |
| **Password Reset** | Email, then code + new password | Two-step reset flow (disabled in enterprise mode) |

![Login page in local mode](../docs/images/login-local.png)

After successful authentication, four values are stored in `localStorage`:

- `observal_api_key` -- sent as `X-API-Key` header on all API requests
- `observal_role` -- cached role for client-side RBAC gating
- `observal_name` -- display name for sidebar
- `observal_email` -- display email for sidebar

### Session Lifecycle

- **401 Interceptor**: If any API call returns HTTP 401 (except `/auth/*` paths), the client clears the session and redirects to `/login?reason=session_expired`.
- **Session Expiry Toast**: On redirect, the login page shows an info toast: "Your session has expired. Please sign in again." The `?reason` param is stripped from the URL immediately.
- **Logout**: The user dropdown menu has a "Sign out" button that calls `clearSession()` and redirects to `/login`.

### RBAC Tiers

The frontend enforces a 4-tier role hierarchy matching the backend:

```
super_admin > admin > reviewer > user
```

| Feature | super_admin | admin | reviewer | user | anonymous |
|---------|:-----------:|:-----:|:--------:|:----:|:---------:|
| Browse registry (home, agents, components, leaderboard) | yes | yes | yes | yes | yes |
| Agent builder | yes | yes | yes | yes | no |
| Submit reviews | yes | yes | yes | yes | no |
| Review queue (approve/reject) | yes | yes | yes | no | no |
| Dashboard, traces, errors, evals, users | yes | yes | no | no | no |
| Settings | yes | no | no | no | no |

**How it works:**

- **`AuthGuard`** -- Wraps routes that require login. Checks for API key in localStorage, calls `/auth/whoami` to resolve role. Redirects to `/login` if unauthenticated.
- **`OptionalAuthGuard`** -- Wraps the registry layout. Allows anonymous browsing. If an API key exists, resolves the role silently. Does NOT redirect.
- **`RoleGuard`** -- Wraps the admin layout. Checks `minRole="admin"`. Shows toast and redirects to `/` if the user's role is insufficient.
- **`useRoleGuard(minRole)`** -- Page-level hook for finer control (e.g., settings page uses `useRoleGuard("super_admin")`).

### Enterprise Mode

When the backend returns `deployment_mode: "enterprise"` from `/api/v1/config/public`:

- The login page shows **only** the "Sign in with SSO" button
- Email/password form, register, API key login, password reset, and all mode-switch links are hidden
- A `useEffect` forces the mode state back to `"login"` if it drifts

<!-- Screenshot: Login page in enterprise mode -- SSO only (WIP) -->

---

## Registry Pages (Public)

### Registry Home (`/`)

The landing page for the agent registry. Accessible without authentication.

**Sections:**

1. **Hero** -- Branding, tagline, live stats bar (agents, components, engineers count), search bar, terminal snippet with copy button (`observal pull my-agent --ide cursor`)
2. **Trending** -- Grid of top 6 agents by download count. Uses `AgentCard` components.
3. **Leaderboard** -- Time-window tabs (24h, 7d, 30d, all time) showing top 10 agents ranked by composite score. Links to full leaderboard.
4. **Recently Added** -- Grid of 6 newest agents sorted by creation date.

![Registry home page](../docs/images/registry-home.png)

### Agent List (`/agents`)

Searchable, sortable list of all agents in the registry.

- **View modes**: Table (default) and grid toggle
- **Table columns**: Name (with description), Downloads, Rating, Version, Status, Updated
- **Sorting**: Click column headers for ascending/descending sort
- **Search**: Debounced text search (300ms) filters by name, description, owner
- **Grid view**: Responsive card layout with `AgentCard` components

![Agent list page](../docs/images/agents-list.png)

### Agent Detail (`/agents/:id`)

Comprehensive agent page with five tabs.

**Header**: Agent name, status badge, version, owner name, description.

**Desktop sidebar**: Pull command (copy button), stats card (downloads, unique users, rating, components, model), publisher info.

**Tabs:**

| Tab | Content |
|-----|---------|
| **Overview** | About section, model name, goal template (structured sections with title + description) |
| **Components** | Linked MCPs/skills/hooks with type badges. Shows system prompt inline if no components linked. |
| **Reviews** | Star rating form (1-5) + text comment for authenticated users. Review list with user, date, rating. |
| **Install** | CLI quick install (`observal pull <name>`), manual IDE config JSON snippet with copy button. |
| **Analytics** | Admin-only tab. Composite score, standard deviation, 95% CI, drift alert. Dimension averages bar chart, score trend, link to traces. |

<!-- Screenshot: Agent detail page -- overview tab with sidebar (WIP -- needs demo data) -->

### Component List (`/components`)

Tabbed list of all component types.

- **Type tabs**: MCPs, Skills, Hooks, Prompts, Sandboxes (click to switch)
- **View modes**: Table and grid toggle (same pattern as agents)
- **Table columns**: Name (with description), Version, Status, Updated
- **Search**: Debounced text search filtered to active type

![Component list -- MCPs tab](../docs/images/components-list.png)

### Component Detail (`/components/:id`)

Individual MCP/skill/hook/prompt/sandbox page.

**Header**: Component name, type badge, status badge, star rating, review count.

**Tabs:**

| Tab | Content |
|-----|---------|
| **Overview** | Dynamic metadata grid (version, git URL, transport, created date, owner, hook type, trigger event, runtime, Docker image, prompt text). Usage metrics. |
| **Reviews** | Same review form and list as agent detail. |
| **Add to Agent** | CLI command (`observal agent add [type] [name]`), git clone source if available. |

<!-- Screenshot: Component detail -- MCP overview tab (WIP -- needs demo data) -->

### Leaderboard (`/agents/leaderboard`)

Full-page leaderboard with expanded rankings.

- **Time windows**: 24h, 7d, 30d, all time tabs
- **Displays**: Top 50 agents ranked with position number, name, owner, download count, rating, version badge
- **Clickable rows**: Navigate to agent detail

![Leaderboard page](../docs/images/leaderboard.png)

### Agent Builder (`/agents/builder`)

Authenticated form to compose and publish new agents. Requires login.

**Left column (2/3):**

1. **Basic Metadata** -- Name (required), description, version (default 1.0.0), model (with Claude model suggestions)
2. **Components** -- Tabbed picker for 5 types (MCPs, Skills, Hooks, Prompts, Sandboxes). Searchable list, drag-to-reorder selected items, real-time validation.
3. **Goal Template** -- Add/remove structured sections (title + content pairs). Validated against selected components.
4. **Publish** -- Creates agent via API, redirects to detail page on success.

**Right column (1/3):**

- **Live Preview** -- Sticky card showing agent name, description, model, selected components, validation status.

![Agent builder with preview panel](../docs/images/agent-builder.png)

---

## Admin Pages

All admin pages require `admin` role or higher. Wrapped in `AuthGuard` + `RoleGuard minRole="admin"`.

### Dashboard (`/dashboard`)

Overview of the entire system.

**Sections:**

1. **Stats Row** -- Agents, Downloads, Users, Components with trend indicators (+/- percentage)
2. **Recent Agents** (2/3 width) -- Table of 10 most recent agents with name, version, status, date
3. **Latest Traces** (2/3 width) -- Table of 8 most recent sessions with session ID, service name, time
4. **Top Downloads** (1/3 width) -- Horizontal bar chart of most-downloaded agents

![Dashboard page](../docs/images/dashboard.png)

### Traces List (`/traces`)

Session explorer for debugging agent interactions.

- **Tabs**: All sessions / Active sessions (auto-refreshing every 10s)
- **Search**: Debounced search across session IDs, models, users
- **Table columns**: Session (with live indicator), Model, User, IDE, Tokens In, API Calls, Tools, Tokens Out, Time
- **Sorting**: Click any column header
- **Kiro sessions**: Detected by service name, display credits instead of tokens
- **Click row**: Navigate to trace detail

![Traces list page](../docs/images/traces.png)

### Trace Detail (`/traces/:id`)

Forensic event viewer for a single agent session. The most complex page in the UI.

**Header**: Session ID, service name, timestamp, duration, turn count. Stats row showing token counts, API calls, tool calls, models used.

**Traces Tab:**

- **Filter Bar** -- 12 category toggles (Prompts, Responses, Thinking, Tools, API, Agents, Lifecycle, Tasks, MCP, Errors, Notifications, Worktrees) with per-category event counts. Free-text search.
- **Event Tree** -- Hierarchical display organized by conversation turns:
  - User prompts (purple blocks)
  - Tool calls with input/output expansion and diff viewer for Edit tools
  - Subagent scopes (nested trees with agent type and token stats)
  - Thinking blocks (chain-of-thought, collapsible)
  - Assistant responses (paginated if >15 lines)
  - Turn end markers with stop reason
- **Toggle All** -- Expand/collapse all events

**Session Info Tab:**

- Metadata grid (session ID, service, source, CWD, permission mode, timestamps, duration, event count)

<!-- Screenshot: Trace detail -- event tree with expanded tool call (WIP -- needs active session) -->

### Errors (`/errors`)

Categorized error event viewer.

- **Error Types**: Tool Failure, Stop Failure, API Error (with count badges and filter buttons)
- **Search**: Free-text search across tools, errors, sessions
- **Expandable Rows**: Click to reveal error message, tool input (JSON formatted), tool response, metadata (session link, agent type, stop reason, user)
- **Color coding**: Amber for tool failures, red for stop failures, rose for API errors

![Errors page](../docs/images/errors.png)

### Evaluations (`/eval`)

Agent evaluation overview.

- **Config Banner**: When no eval model is configured (`EVAL_MODEL_NAME` not set), shows an amber warning banner explaining how to set it up. Page content is grayed out.
- **Agent Cards**: Grid of all agents with latest grade (A-F, color-coded), score (/10), eval count, "View Details" and "Run" buttons.

![Eval page with config banner](../docs/images/eval-no-config.png)

### Eval Detail (`/eval/:agentId`)

Detailed evaluation metrics for a single agent.

**Left column (2/3):**

- **Score Over Time** -- Line/area chart of composite scores
- **Scorecard History** -- Table with date, version, score, grade (color-coded badge), penalty count

**Right column (1/3):**

- **Current Score** -- Large grade display with numeric score and version
- **Dimensions Radar Chart** -- Polar visualization of dimension scores
- **Recommendations** -- Bulleted improvement suggestions from latest scorecard
- **Penalties** -- Expandable accordion with severity and details

<!-- Screenshot: Eval detail -- score chart and current grade (WIP -- needs eval data) -->

### Review Queue (`/review`)

Approve or reject submitted agents and components. Requires `reviewer` role or higher.

- **View modes**: Grid (default) and list toggle
- **Grid view**: Cards with name, type badge, submitter, date, validation status, approve/reject buttons
- **List view**: Compact rows with inline reject reason input
- **Validation badges**: Green "Validated", amber "Has warnings", red "Validation failed" (with expandable quality warnings)
- **Reject flow**: Click reject, inline input for reason, confirm
- **Empty state**: "All clear" when no pending submissions

![Review queue](../docs/images/review.png)

### Users (`/users`)

User management for admins.

- **User table**: Name, email, role dropdown (live-update via API), join date
- **Role dropdown**: Super Admin, Admin, Reviewer, Viewer (changes role immediately on selection)
- **Add User**: Dialog with name, email, role fields. On creation, shows the generated API key with copy button and warning: "Save this API key -- it will not be shown again."
- **User count**: Displayed above table

![Users page with role dropdowns](../docs/images/users.png)

### Settings (`/settings`)

System configuration. **Super admin only** -- not visible to admin or lower roles.

**Sections:**

1. **System Overview** -- Read-only status panel showing:
   - Deployment Mode (`local` or `enterprise`)
   - SSO status (Enabled/Disabled)
   - Eval Model status (Configured/Not configured)
   - Enterprise mode info note when active

2. **Active Settings** -- Key-value table with inline edit and delete. Hover to reveal edit/delete icons.

3. **Suggested Settings** -- Clickable cards for common settings not yet configured:
   - `telemetry.otlp_endpoint` -- OpenTelemetry collector endpoint
   - `telemetry.enabled` -- Enable/disable telemetry collection
   - `registry.auto_approve` -- Auto-approve new submissions
   - `registry.max_agents_per_user` -- Maximum agents per user
   - `eval.default_window_size` -- Default eval window size

4. **Add Setting** -- Form to add custom key-value settings.

![Settings page with system overview](../docs/images/settings.png)

---

## Navigation

### Sidebar

The sidebar is organized into three groups, each gated by role:

| Group | Items | Minimum Role |
|-------|-------|-------------|
| **Registry** | Home, Agents, Leaderboard, Components, Builder | Anonymous (Builder requires auth) |
| **Review** | Review | `reviewer` |
| **Admin** | Dashboard, Traces, Errors, Evals, Users, Settings | `admin` (Settings requires `super_admin`) |

**Footer**: Theme switcher (light/dark/system) and user dropdown (avatar, name, email, account settings link, sign out).

### Command Palette

Activated with **Cmd/Ctrl+K**. Provides keyboard-accessible navigation:

- **Search**: Filter all navigation items and quick actions
- **Navigate**: All sidebar items with icons
- **Quick Actions**:
  - `+ New Agent` -> `/agents/builder`
  - `? Search Agents` -> `/agents?search=`
  - `? Search Components` -> `/components?search=`

---

## Design Patterns

### Layout

All pages follow a consistent structure:

```
<PageHeader title="..." breadcrumbs={[...]} actionButtonsRight={...} />
<div className="p-6 w-full max-w-6xl mx-auto space-y-N">
  {/* Page content */}
</div>
```

- `SidebarInset` provides `w-full flex-1` to the main content area
- Content wrappers use `w-full max-w-6xl mx-auto` for consistent centering (some pages use `max-w-4xl` or `max-w-[1200px]` for narrower/wider layouts)
- Registry list pages use `max-w-[1200px]` for wider table layouts

### Loading States

- **Skeletons**: `CardSkeleton`, `TableSkeleton`, `DetailSkeleton` components provide content-shaped loading placeholders
- **Empty States**: `EmptyState` component with icon, title, description, and optional action button
- **Error States**: `ErrorState` component with error message and retry button
- **Animation**: Pages use `animate-in` and `stagger-N` classes for sequenced entrance animations

### Data Fetching

All data fetching uses TanStack Query (React Query) via custom hooks in `web/src/hooks/use-api.ts`:

- `useRegistryList(type, params)` -- List agents or components with search
- `useRegistryDetail(id)` -- Single agent or component
- `useOtelSessions(options)` -- Trace sessions list
- `useOtelSessionDetail(id)` -- Single session events
- `useAdminUsers()`, `useAdminSettings()` -- Admin data
- `useEvalScorecards(agentId)`, `useEvalRun()` -- Eval data
- `useReviewList()`, `useReviewAction()` -- Review queue
- `useOverviewStats()`, `useTopAgents()`, `useLeaderboard(window, limit)` -- Dashboard data

### Deployment Config Hook

`useDeploymentConfig()` fetches `/api/v1/config/public` (cached 5 minutes) and returns:

```typescript
{
  deploymentMode: "local" | "enterprise",
  ssoEnabled: boolean,
  samlEnabled: boolean,
  evalConfigured: boolean,
  loading: boolean,
}
```

Used by the login page (enterprise gating), eval page (config banner), and settings page (system overview).
