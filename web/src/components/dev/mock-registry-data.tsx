// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * Development-only mock data for visual QA of Registry surfaces.
 *
 * Enable:  set  VITE_MOCK_REGISTRY=1  in your shell or .env.local
 * Remove:  delete this file and the <MockRegistryData /> mount in _authed.tsx
 *
 * This component seeds the React Query cache with realistic fixture data
 * so every Registry tab renders populated content. It does NOT modify any
 * hook, API module, or production code path.
 */

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type {
  RegistryItem,
  TopAgentItem,
  LeaderboardItem,
  ComponentLeaderboardItem,
  Session,
  RecommendationsResponse,
} from "@/lib/types";
import type { Team } from "@/lib/types";

// ── Feature gate ────────────────────────────────────────────────────

const ENABLED =
  typeof import.meta !== "undefined" &&
  import.meta.env?.VITE_MOCK_REGISTRY === "1";

// ── Agents ──────────────────────────────────────────────────────────

function id() {
  return crypto.randomUUID();
}
function ago(minutes: number) {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

const AGENTS: RegistryItem[] = [
  {
    id: id(), name: "Secure Reviewer", namespace: "acme", slug: "secure-reviewer",
    qualified_name: "acme/secure-reviewer", description: "Reviews diffs for security regressions, risky dependencies, and leaked secrets. Supports Python, Go, TypeScript.",
    status: "approved", version: "2.3.0", download_count: 12_840, average_rating: 4.9,
    component_count: 5, supported_harnesses: ["claude-code", "pi", "codex", "kiro", "cursor"],
    created_by_username: "maya", owner: "maya@acme.dev", created_at: ago(43200), updated_at: ago(120),
  },
  {
    id: id(), name: "Repository Analyst", namespace: "github", slug: "repository-analyst",
    qualified_name: "github/repository-analyst", description: "Maps unfamiliar repositories and produces evidence-backed change plans.",
    status: "approved", version: "3.4.0", download_count: 18_200, average_rating: 4.9,
    component_count: 4, supported_harnesses: ["claude-code", "pi", "codex", "kiro", "cursor", "copilot", "opencode", "goose"],
    created_by_username: "github-bot", owner: "platform@github.com", created_at: ago(86400), updated_at: ago(180),
  },
  {
    id: id(), name: "Release Pilot", namespace: "platform", slug: "release-pilot",
    qualified_name: "platform/release-pilot", description: "Coordinates release notes, verification gates, and deployment handoffs across microservices.",
    status: "pending", version: "4.1.0", download_count: 8_400, average_rating: 4.8,
    component_count: 6, supported_harnesses: ["claude-code", "pi", "codex"],
    created_by_username: "jon", owner: "jon@acme.dev", created_at: ago(14400), updated_at: ago(60),
  },
  {
    id: id(), name: "Test Architect", namespace: "dx", slug: "test-architect",
    qualified_name: "dx/test-architect", description: "Turns product behavior specs into maintainable, risk-based test plans and implementation scaffolds.",
    status: "approved", version: "1.9.2", download_count: 11_600, average_rating: 4.8,
    component_count: 3, supported_harnesses: ["claude-code", "pi", "codex", "kiro", "cursor", "copilot"],
    created_by_username: "ava", owner: "ava@acme.dev", created_at: ago(172800), updated_at: ago(7200),
  },
  {
    id: id(), name: "Incident Responder", namespace: "infra", slug: "incident-responder",
    qualified_name: "infra/incident-responder", description: "Correlates traces, logs, and recent code changes during production incidents.",
    status: "approved", version: "2.1.4", download_count: 9_400, average_rating: 4.7,
    component_count: 7, supported_harnesses: ["claude-code", "pi", "codex", "kiro", "cursor"],
    created_by_username: "liam", owner: "liam@acme.dev", created_at: ago(259200), updated_at: ago(14400),
  },
  {
    id: id(), name: "Docs Maintainer", namespace: "open-source", slug: "docs-maintainer",
    qualified_name: "open-source/docs-maintainer", description: "Keeps technical documentation aligned with APIs, changelogs, and release notes across multiple repositories.",
    status: "approved", version: "1.6.0", download_count: 7_900, average_rating: 4.7,
    component_count: 3, supported_harnesses: ["claude-code", "pi", "codex", "kiro", "cursor", "copilot", "opencode"],
    created_by_username: "sofia", owner: "sofia@acme.dev", created_at: ago(345600), updated_at: ago(43200),
  },
  {
    id: id(), name: "Support Drafter", namespace: "cx", slug: "support-drafter",
    qualified_name: "cx/support-drafter", description: "Drafts accurate customer replies grounded in approved knowledge base articles.",
    status: "approved", version: "1.2.0", download_count: 2_400, average_rating: 4.5,
    component_count: 2, supported_harnesses: ["claude-code", "pi"],
    created_by_username: "priya", owner: "priya@acme.dev", created_at: ago(604800), updated_at: ago(86400),
  },
  {
    id: id(), name: "Schema Guide", namespace: "data", slug: "schema-guide",
    qualified_name: "data/schema-guide", description: "Plans safe, reversible database schema migrations with rollback steps for PostgreSQL and ClickHouse.",
    status: "approved", version: "0.8.1", download_count: 1_200, average_rating: 4.3,
    component_count: 2, supported_harnesses: ["claude-code", "pi", "codex"],
    created_by_username: "casey", owner: "casey@acme.dev", created_at: ago(172800), updated_at: ago(28800),
  },
];

const MY_AGENTS: RegistryItem[] = [
  {
    id: id(), name: "Migration Guide", namespace: "acme", slug: "migration-guide",
    qualified_name: "acme/migration-guide", description: "Plans safe, reversible database and infrastructure migrations.",
    status: "draft", version: "0.4.0", download_count: 0, component_count: 3,
    created_by_username: "admin", owner: "admin@localhost", created_at: ago(7200), updated_at: ago(300),
  },
  {
    id: id(), name: "Release Pilot", namespace: "platform", slug: "release-pilot",
    qualified_name: "platform/release-pilot", description: "Coordinates release notes, verification gates, and deployment handoffs.",
    status: "pending", version: "4.1.0", download_count: 8_400, average_rating: 4.8,
    component_count: 6, created_by_username: "admin", owner: "admin@localhost",
    created_at: ago(14400), updated_at: ago(60),
  },
];

const TOP_AGENTS: TopAgentItem[] = AGENTS.slice(0, 6).map((a) => ({
  id: a.id, name: a.name, namespace: a.namespace, slug: a.slug,
  qualified_name: a.qualified_name, description: a.description ?? "",
  owner: (a.owner as string) ?? "", created_by_username: a.created_by_username as string,
  version: (a.version as string) ?? "1.0.0",
  download_count: (a.download_count as number) ?? 0,
  average_rating: (a.average_rating as number) ?? null,
}));

const LEADERBOARD: LeaderboardItem[] = TOP_AGENTS.map((a) => ({
  ...a, created_by_email: `${a.created_by_username}@acme.dev`,
}));

// ── Components ──────────────────────────────────────────────────────

function comp(type: string, ns: string, slug: string, name: string, desc: string, dl: number, rating: number | null, ver: string, status = "approved"): RegistryItem {
  return {
    id: id(), name, namespace: ns, slug, qualified_name: `${ns}/${slug}`,
    description: desc, status, version: ver, download_count: dl,
    average_rating: rating, component_type: type,
    created_at: ago(86400), updated_at: ago(3600),
    created_by_username: ns, owner: `${ns}@acme.dev`,
  };
}

const MCPS: RegistryItem[] = [
  comp("mcp", "github", "github-mcp", "GitHub MCP", "Repository, issue, pull-request, and workflow tools for any GitHub-hosted project.", 12_100, 4.9, "1.12.0"),
  comp("mcp", "data", "postgres-tools", "Postgres Tools", "Read-only schema exploration and safe parameterised query execution.", 8_400, 4.8, "2.4.1"),
  comp("mcp", "observability", "sentry-mcp", "Sentry MCP", "Issue context, stack traces, and release correlation from Sentry.", 5_200, 4.6, "1.8.0"),
  comp("mcp", "product", "linear-mcp", "Linear MCP", "Issues, projects, cycles, and product-planning context from Linear.", 3_800, 4.5, "1.6.3"),
  comp("mcp", "infra", "aws-context", "AWS Context", "Read-only access to CloudWatch metrics, ECS service state, and recent deploys.", 2_900, 4.4, "0.9.2"),
  comp("mcp", "docs", "confluence-mcp", "Confluence MCP", "Search and retrieve pages from Confluence spaces.", 1_600, 4.2, "0.7.0", "pending"),
];

const SKILLS: RegistryItem[] = [
  comp("skill", "security", "threat-model", "Threat Model", "Structured threat modelling for application changes using STRIDE and attack trees.", 6_800, 4.8, "3.0.2"),
  comp("skill", "dx", "release-notes", "Release Notes", "Generate clear customer-facing release notes from merged pull requests.", 4_200, 4.6, "2.1.0"),
  comp("skill", "quality", "code-review", "Code Review Skill", "Structured review covering correctness, security, performance, and readability.", 3_100, 4.5, "1.4.1"),
];

const HOOKS: RegistryItem[] = [
  comp("hook", "platform", "session-push", "Session Push", "Reliable session delivery with local outbox and automatic retries.", 9_800, 4.9, "1.9.0"),
  comp("hook", "security", "secret-scanner", "Secret Scanner", "Check changed files for credentials before tools save or publish.", 5_400, 4.7, "2.0.1"),
  comp("hook", "quality", "lint-gate", "Lint Gate", "Blocks agent output that introduces lint errors in modified files.", 2_100, 4.3, "1.1.0"),
];

const PROMPTS: RegistryItem[] = [
  comp("prompt", "architecture", "design-review", "Architecture Review", "A reusable prompt for structured design and trade-off reviews.", 4_600, 4.7, "1.3.0"),
  comp("prompt", "hiring", "interview-prep", "Interview Prep", "Prepare structured technical interview questions from a job description.", 1_800, 4.2, "0.5.0"),
];

const SANDBOXES: RegistryItem[] = [
  comp("sandbox", "compute", "python-sandbox", "Python Sandbox", "Isolated Python 3.12 environment with scientific computing libraries pre-installed.", 3_200, 4.4, "1.0.3"),
  comp("sandbox", "compute", "node-sandbox", "Node Sandbox", "Node.js 22 sandbox with npm, TypeScript, and common dev tools.", 1_400, 4.1, "0.6.0"),
];

const ALL_COMPONENTS: Record<string, RegistryItem[]> = {
  mcps: MCPS, skills: SKILLS, hooks: HOOKS, prompts: PROMPTS, sandboxes: SANDBOXES,
};

const COMP_LEADERBOARD: ComponentLeaderboardItem[] = [
  ...MCPS, ...SKILLS, ...HOOKS, ...PROMPTS, ...SANDBOXES,
].sort((a, b) => ((b.download_count as number) ?? 0) - ((a.download_count as number) ?? 0))
  .slice(0, 15)
  .map((c) => ({
    id: c.id, name: c.name, namespace: c.namespace, slug: c.slug,
    qualified_name: c.qualified_name,
    component_type: (c.component_type as string) ?? "mcp",
    description: c.description ?? "",
    download_count: (c.download_count as number) ?? 0,
    created_by_email: (c.owner as string) ?? "",
    average_rating: (c.average_rating as number) ?? null,
    total_reviews: Math.floor(Math.random() * 80) + 5,
  }));

// ── Teams ───────────────────────────────────────────────────────────

const TEAMS: Team[] = [
  { id: id(), name: "Platform Engineering", handle: "platform", description: "Core product, platform, web, mobile, and data teams.", visibility: "private", role: "owner", member_count: 14, created_at: ago(259200) },
  { id: id(), name: "Developer Experience", handle: "dx", description: "Shared developer tooling, onboarding workflows, and quality automation.", visibility: "private", role: "member", member_count: 9, created_at: ago(172800) },
  { id: id(), name: "Security Engineering", handle: "security", description: "Secure development guidance, review agents, and policy components.", visibility: "private", role: "member", member_count: 7, created_at: ago(345600) },
  { id: id(), name: "Data Platform", handle: "data", description: "Warehouse operations, schema migrations, and analytics engineering.", visibility: "private", role: null, member_count: 11, created_at: ago(604800), visibility_request_status: "pending" },
  { id: id(), name: "Open Source", handle: "open-source", description: "Community-maintained agents and reusable components available to everyone.", visibility: "public", role: null, member_count: 23, created_at: ago(1296000), visibility_request_status: "approved" },
];

// ── Sessions ────────────────────────────────────────────────────────

const SESSIONS: Session[] = [
  { session_id: "ses_01JY8P6MZQ", first_event_time: ago(18), last_event_time: ago(1), is_active: true, prompt_count: 14, api_request_count: 42, tool_result_count: 38, total_input_tokens: 312_000, total_output_tokens: 116_000, model: "claude-sonnet-4-20250514", service_name: "pi", platform: "Pi", agent_name: "secure-reviewer", agent_version: "2.3.0" },
  { session_id: "ses_01JY8MBZ4K", first_event_time: ago(42), last_event_time: ago(24), prompt_count: 9, api_request_count: 27, tool_result_count: 24, total_input_tokens: 218_000, total_output_tokens: 94_000, model: "claude-opus-4-20250514", service_name: "claude_code", platform: "Claude Code", agent_name: "repository-analyst", agent_version: "3.4.0" },
  { session_id: "ses_01JY8J7AZC", first_event_time: ago(83), last_event_time: ago(42), prompt_count: 22, api_request_count: 19, tool_result_count: 16, total_input_tokens: 186_000, total_output_tokens: 100_000, model: "claude-sonnet-4-20250514", service_name: "kiro", platform: "Kiro", agent_name: "migration-guide", agent_version: "0.4.0" },
  { session_id: "ses_01JY8F9N21", first_event_time: ago(128), last_event_time: ago(105), prompt_count: 16, api_request_count: 31, tool_result_count: 28, total_input_tokens: 251_000, total_output_tokens: 100_000, model: "gpt-4.1-2025-04-14", service_name: "cursor", platform: "Cursor", agent_name: "test-architect", agent_version: "1.9.2" },
];

// ── Recommendations ─────────────────────────────────────────────────

const RECS: RecommendationsResponse = {
  personalized: true,
  profile_sessions: 12,
  topics: ["authentication", "database", "testing"],
  items: [
    { type: "mcp", id: MCPS[0].id, name: "GitHub MCP", namespace: "github", slug: "github-mcp", qualified_name: "github/github-mcp", description: "Used by 8 of your 12 installed agents. The latest release addresses permission retries seen in two traces.", category: "Developer Tools", latest_version: "1.12.0", download_count: 12_100, matched_on: ["tools_used", "agent_dependency"], score: 0.96, reason: "8 of your agents depend on this MCP and the latest version fixes retries you hit in 2 sessions" },
    { type: "skill", id: SKILLS[0].id, name: "Threat Model", namespace: "security", slug: "threat-model", qualified_name: "security/threat-model", description: "Fourteen recent sessions changed authentication or authorization code.", category: "Security", latest_version: "3.0.2", download_count: 6_800, matched_on: ["session_topic"], score: 0.91, reason: "14 recent sessions touched auth code — this skill adds structured threat modelling" },
    { type: "agent", id: AGENTS[3].id, name: "Test Architect", namespace: "dx", slug: "test-architect", qualified_name: "dx/test-architect", description: "Developer Experience used this in 28 successful sessions during the last seven days.", category: "Quality", latest_version: "1.9.2", download_count: 11_600, matched_on: ["team_usage"], score: 0.88, reason: "Your team used this agent 28 times in the last 7 days with a 96% success rate" },
  ],
};

// ── Cache seeder ────────────────────────────────────────────────────

export function MockRegistryData() {
  const qc = useQueryClient();

  useEffect(() => {
    if (!ENABLED) return;
    console.info("[mock] Seeding Registry fixture data (VITE_MOCK_REGISTRY=1)");

    // Whoami
    qc.setQueryData(["auth", "whoami"], {
      id: "usr_mock_admin", email: "admin@localhost", name: "Naraen Ram",
      username: "naraen", role: "admin",
    });

    // Agents
    qc.setQueryData(["registry", "agents", undefined], AGENTS);
    qc.setQueryData(["registry", "agents", {}], AGENTS);
    qc.setQueryData(["registry", "agents", "my"], MY_AGENTS);
    qc.setQueryData(["registry", "agents", "archived"], []);
    qc.setQueryData(["registry", "agents", "deleted"], []);
    qc.setQueryData(["overview", "top-agents", 6], TOP_AGENTS);

    // Agent detail — seed each so clicking into them works
    for (const a of AGENTS) {
      qc.setQueryData(["registry", "agents", a.id], a);
      if (a.namespace && a.slug) {
        qc.setQueryData(["registry-resolve", "agents", `${a.namespace}/${a.slug}`], {
          id: a.id, type: "agents", namespace: a.namespace, slug: a.slug,
          qualified_name: a.qualified_name,
        });
      }
    }

    // Components
    for (const [type, items] of Object.entries(ALL_COMPONENTS)) {
      qc.setQueryData(["registry", type, undefined], items);
      qc.setQueryData(["registry", type, {}], items);
      for (const c of items) {
        qc.setQueryData(["registry", type, c.id], c);
        if (c.namespace && c.slug) {
          qc.setQueryData(["registry-resolve", type, `${c.namespace}/${c.slug}`], {
            id: c.id, type, namespace: c.namespace, slug: c.slug,
            qualified_name: c.qualified_name,
          });
        }
      }
    }

    // Leaderboard
    qc.setQueryData(["leaderboard", "7d", 50, undefined], LEADERBOARD);
    qc.setQueryData(["leaderboard", "24h", 50, undefined], LEADERBOARD.slice(0, 3));
    qc.setQueryData(["leaderboard", "30d", 50, undefined], LEADERBOARD);
    qc.setQueryData(["leaderboard", "all", 50, undefined], LEADERBOARD);
    qc.setQueryData(["component-leaderboard", "7d", 50], COMP_LEADERBOARD);
    qc.setQueryData(["component-leaderboard", "24h", 50], COMP_LEADERBOARD.slice(0, 5));
    qc.setQueryData(["component-leaderboard", "30d", 50], COMP_LEADERBOARD);
    qc.setQueryData(["component-leaderboard", "all", 50], COMP_LEADERBOARD);

    // Teams
    qc.setQueryData(["teams"], TEAMS);
    qc.setQueryData(["teams", "all"], TEAMS);
    for (const t of TEAMS) {
      qc.setQueryData(["teams", "by-handle", t.handle], t);
      qc.setQueryData(["teams", t.id, "members"], [
        { id: id(), email: "admin@localhost", username: "naraen", name: "Naraen Ram", role: "owner" },
        { id: id(), email: "maya@acme.dev", username: "maya", name: "Maya Chen", role: "reviewer" },
        { id: id(), email: "liam@acme.dev", username: "liam", name: "Liam Shah", role: "member" },
      ]);
    }

    // Sessions
    qc.setQueryData(["sessions", "list", undefined, undefined, 7, 8, undefined, true], SESSIONS);

    // Recommendations
    qc.setQueryData(["recommendations", "me", 3, "all"], RECS);

    // Sessions summary
    qc.setQueryData(["sessions", "summary"], { total_sessions: 148, today_sessions: 12 });

    // Inbox counts
    qc.setQueryData(["inbox", "count", false, null], { unread: 3, action_required: 1 });
  }, [qc]);

  if (!ENABLED) return null;

  return (
    <div className="fixed bottom-3 left-3 z-[200] rounded-lg bg-warning/90 px-3 py-1.5 text-[10px] font-mono font-semibold text-warning-foreground shadow-lg">
      MOCK DATA
    </div>
  );
}
