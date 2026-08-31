// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { Link, useRouter } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Blocks,
  Bot,
  Search,
  Star,
} from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { RecommendedForYou } from "@/components/registry/recommended-for-you";
import { RegistryName } from "@/components/registry/registry-name";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorState } from "@/components/shared/error-state";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import {
  useMyAgents,
  useRegistryList,
  useSessions2,
  useTopAgents,
  useWhoami,
} from "@/hooks/use-api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { registryItemPath } from "@/lib/registry-name";
import { compactNumber } from "@/lib/utils";
import type { RegistryItem, Session, TopAgentItem } from "@/lib/types";

const TIME_FORMATTER = new Intl.DateTimeFormat("en", {
  hour: "numeric",
  minute: "2-digit",
});

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

function toNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

function formatTime(value?: string): string {
  if (!value) return "No activity";
  const parsed = new Date(
    value.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(value)
      ? value
      : `${value.replace(" ", "T")}Z`,
  );
  if (Number.isNaN(parsed.getTime())) return "No activity";
  return parsed.toDateString() === new Date().toDateString()
    ? TIME_FORMATTER.format(parsed)
    : DATE_TIME_FORMATTER.format(parsed);
}

function isApproved(agent: RegistryItem): boolean {
  return !agent.status || agent.status === "approved";
}

function sessionTitle(session: Session): string {
  const prompts = toNumber(session.prompt_count);
  return `${session.agent_name ? `${session.agent_name} · ` : ""}${prompts} ${prompts === 1 ? "prompt" : "prompts"}`;
}

function sessionPlatform(session: Session): string {
  return session.platform || session.service_name || "Unknown harness";
}

function PanelHeader({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="flex min-h-16 items-center justify-between gap-5 border-b border-border px-4 py-3">
      <div className="min-w-0">
        <h2 className="text-base font-semibold tracking-tight text-foreground">
          {title}
        </h2>
        <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </header>
  );
}

function AgentRow({ agent }: { agent: TopAgentItem }) {
  return (
    <Link
      to={registryItemPath(agent, "agents", agent.id)}
      className="group grid min-h-18 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-b border-border/75 px-4 py-3 last:border-b-0 hover:bg-accent/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring md:grid-cols-[minmax(0,1fr)_5rem_6rem_5rem_1.5rem]"
    >
      <div className="min-w-0">
        <RegistryName
          item={agent}
          nameClassName="text-sm font-semibold text-foreground group-hover:text-primary-accent"
        />
        <p className="mt-1 line-clamp-1 text-sm text-muted-foreground">
          {agent.description}
        </p>
      </div>
      <span className="hidden font-mono text-xs text-muted-foreground md:block">
        v{agent.version}
      </span>
      <span className="hidden items-center justify-end gap-1.5 text-xs text-muted-foreground md:inline-flex">
        <ArrowDownToLine className="h-3.5 w-3.5" />
        {compactNumber(agent.download_count)}
      </span>
      <span className="hidden items-center justify-end gap-1.5 text-xs text-muted-foreground md:inline-flex">
        <Star className="h-3.5 w-3.5" />
        {agent.average_rating ? agent.average_rating.toFixed(1) : "New"}
      </span>
      <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
    </Link>
  );
}

function AvailableAgentRow({ agent }: { agent: RegistryItem }) {
  return (
    <Link
      to={registryItemPath(agent, "agents", agent.id)}
      className="group grid min-h-18 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-b border-border/75 px-4 py-3 last:border-b-0 hover:bg-accent/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <div className="min-w-0">
        <RegistryName
          item={agent}
          nameClassName="text-sm font-semibold text-foreground group-hover:text-primary-accent"
        />
        <p className="mt-1 line-clamp-1 text-sm text-muted-foreground">
          {typeof agent.description === "string"
            ? agent.description
            : "Approved agent"}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <span className="font-mono text-xs text-muted-foreground">
          {typeof agent.version === "string" ? `v${agent.version}` : "Latest"}
        </span>
        <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
      </div>
    </Link>
  );
}

function SessionRow({ session }: { session: Session }) {
  return (
    <Link
      to="/traces/$traceId"
      params={{ traceId: session.session_id }}
      className="group block border-b border-border/75 px-4 py-3 last:border-b-0 hover:bg-accent/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="truncate text-sm font-semibold text-foreground group-hover:text-primary-accent">
          {sessionTitle(session)}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">
          {formatTime(session.last_event_time)}
        </span>
      </div>
      <p className="mt-1 truncate text-sm text-muted-foreground">
        {sessionPlatform(session)} · {session.model || "Unknown model"} ·{" "}
        {compactNumber(toNumber(session.tool_result_count))} tools
      </p>
    </Link>
  );
}

type WorkRoute = "/agents" | "/agents/builder" | "/components";

function WorkRow({
  href,
  icon: Icon,
  title,
  description,
}: {
  href: WorkRoute;
  icon: typeof Bot;
  title: string;
  description: string;
}) {
  return (
    <Link
      to={href}
      className="group grid min-h-18 grid-cols-[1.25rem_minmax(0,1fr)_1rem] gap-3 border-b border-border/75 px-4 py-3 last:border-b-0 hover:bg-accent/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <Icon className="mt-0.5 h-4 w-4 text-component-agent" />
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-foreground">
          {title}
        </span>
        <span className="mt-1 block text-sm leading-5 text-muted-foreground">
          {description}
        </span>
      </span>
      <ArrowRight className="mt-0.5 h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
    </Link>
  );
}

export default function RegistryHome() {
  const [search, setSearch] = useState("");
  const router = useRouter();
  const { data: whoami } = useWhoami();
  const { brandingAppName } = useDeploymentConfig();
  const { data: sessions, isLoading: sessionsLoading } = useSessions2({
    days: 7,
    limit: 8,
    mine: true,
    refetchInterval: 30_000,
  });
  const { data: myAgents, isLoading: myAgentsLoading } = useMyAgents();
  const { data: topAgents, isLoading: topAgentsLoading } = useTopAgents(6);
  const {
    data: agents,
    isLoading: agentsLoading,
    isError: agentsError,
    error: agentsErrorDetail,
    refetch: refetchAgents,
  } = useRegistryList("agents");

  const approvedAgents = useMemo(
    () => (agents ?? []).filter(isApproved),
    [agents],
  );
  const workInProgress = useMemo(
    () =>
      (myAgents ?? []).filter((agent) =>
        ["draft", "pending", "rejected"].includes(
          typeof agent.status === "string" ? agent.status : "",
        ),
      ),
    [myAgents],
  );
  const trustedAgents = useMemo(
    () => approvedAgents.slice(0, 5),
    [approvedAgents],
  );
  const recentSessions = (sessions ?? []).slice(0, 4);
  const displayName =
    whoami?.name || whoami?.username || whoami?.email || "Welcome back";
  const daySummary =
    myAgentsLoading || sessionsLoading
      ? "Loading your registry activity."
      : `${workInProgress.length} registry item${workInProgress.length === 1 ? "" : "s"} need attention · ${(sessions ?? []).length} recent session${(sessions ?? []).length === 1 ? "" : "s"} captured.`;

  function handleSearch(event: React.FormEvent) {
    event.preventDefault();
    const query = search.trim();
    if (query) router.navigate({ to: "/agents", search: { search: query } });
  }

  return (
    <>
      <PageHeader title="Registry" />

      <div className="mx-auto w-full max-w-[90rem] space-y-8 px-4 py-7 sm:px-6 lg:px-10 lg:py-9">
        <section className="max-w-5xl">
          <h1 className="max-w-3xl text-balance text-2xl font-semibold tracking-[-0.03em] text-foreground sm:text-3xl">
            {displayName}, here is your day in {brandingAppName || "Observal"}.
          </h1>
          <p className="mt-2 max-w-2xl text-base leading-7 text-muted-foreground">
            {daySummary}
          </p>

          <form onSubmit={handleSearch} className="mt-7 flex max-w-4xl gap-2">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                aria-label="Search agents"
                placeholder="Search agents"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="h-12 rounded-md border-input bg-card pl-10 text-base shadow-none"
              />
            </div>
            <Button
              type="submit"
              className="h-12 shrink-0 px-5"
              disabled={!search.trim()}
            >
              Search
            </Button>
          </form>

          <nav
            aria-label="Browse registry"
            className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm"
          >
            <Link
              to="/agents"
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              Browse all agents
            </Link>
            <Link
              to="/components"
              search={{ type: "mcps" }}
              className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            >
              MCP servers
            </Link>
            <Link
              to="/components"
              search={{ type: "skills" }}
              className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            >
              Skills
            </Link>
            <Link
              to="/components"
              search={{ type: "hooks" }}
              className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            >
              Hooks
            </Link>
            <Link
              to="/teamspaces"
              className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            >
              Teamspaces
            </Link>
          </nav>
        </section>

        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_21rem]">
          <RecommendedForYou limit={3} />

          <section className="overflow-hidden rounded-md border border-border bg-card">
            <PanelHeader
              title="Your work"
              description="Publishing and maintenance that needs you."
            />
            <WorkRow
              href="/agents"
              icon={Bot}
              title={
                myAgentsLoading
                  ? "Loading your work"
                  : workInProgress.length > 0
                    ? `${workInProgress.length} item${workInProgress.length === 1 ? "" : "s"} need attention`
                    : "Your agents are up to date"
              }
              description={
                workInProgress.length > 0
                  ? "Open drafts, pending reviews, and rejected submissions."
                  : "Review published agents or start a new release."
              }
            />
            <WorkRow
              href="/agents/builder"
              icon={Bot}
              title="Build an agent"
              description="Bundle components into a portable, versioned agent."
            />
            <WorkRow
              href="/components"
              icon={Blocks}
              title="Browse components"
              description="Find MCPs, skills, hooks, prompts, and sandboxes."
            />
          </section>

          <section className="overflow-hidden rounded-md border border-border bg-card">
            <PanelHeader
              title={topAgents?.length ? "Agents gaining adoption" : "Trusted agents"}
              description={
                topAgents?.length
                  ? "Frequently installed agents from across the registry."
                  : "Approved agents available to install now."
              }
              action={
                <Link
                  to="/leaderboard"
                  className="shrink-0 text-sm font-medium text-primary-accent underline-offset-4 hover:underline"
                >
                  Leaderboard
                </Link>
              }
            />
            {topAgentsLoading || agentsLoading ? (
              <div className="p-3">
                <TableSkeleton rows={5} cols={4} />
              </div>
            ) : topAgents?.length ? (
              topAgents.map((agent) => <AgentRow key={agent.id} agent={agent} />)
            ) : agentsError ? (
              <div className="p-5">
                <ErrorState
                  message={agentsErrorDetail?.message}
                  onRetry={() => refetchAgents()}
                />
              </div>
            ) : trustedAgents.length > 0 ? (
              trustedAgents.map((agent) => (
                <AvailableAgentRow key={agent.id} agent={agent} />
              ))
            ) : (
              <p className="p-6 text-sm text-muted-foreground">
                Approved agents will appear here when your registry starts publishing.
              </p>
            )}
          </section>

          <section className="overflow-hidden rounded-md border border-border bg-card">
            <PanelHeader
              title="Recent execution"
              description="Your latest captured coding sessions."
              action={
                <Link
                  to="/traces"
                  className="shrink-0 text-sm font-medium text-primary-accent underline-offset-4 hover:underline"
                >
                  All traces
                </Link>
              }
            />
            {sessionsLoading ? (
              <div className="p-3">
                <TableSkeleton rows={4} cols={2} />
              </div>
            ) : recentSessions.length === 0 ? (
              <div className="flex gap-3 p-5 text-sm leading-6 text-muted-foreground">
                <Activity className="mt-1 h-4 w-4 shrink-0" />
                Enable telemetry in a supported harness to connect registry assets
                with execution evidence.
              </div>
            ) : (
              recentSessions.map((session) => (
                <SessionRow key={session.session_id} session={session} />
              ))
            )}
          </section>
        </div>
      </div>
    </>
  );
}
