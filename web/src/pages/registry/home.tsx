// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { Link, useRouter } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Bot,
  CircleAlert,
  Clock3,
  FileEdit,
  Gauge,
  Medal,
  Search,
  Sparkles,
  Star,
  Terminal,
  Trophy,
  WandSparkles,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { AgentCard } from "@/components/registry/agent-card";
import { PageHeader } from "@/components/layouts/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CardSkeleton, TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import {
  useLeaderboard,
  useMyAgents,
  useRegistryList,
  useSessions2,
  useTopAgents,
  useWhoami,
} from "@/hooks/use-api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { compactNumber, formatNumber } from "@/lib/utils";
import type { LeaderboardItem, RegistryItem, Session, TopAgentItem } from "@/lib/types";

const TOKEN_FORMATTER = Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const TIME_FORMATTER = new Intl.DateTimeFormat("en", { hour: "numeric", minute: "2-digit" });

interface HomeAction {
  title: string;
  description: string;
  href: string;
  icon: LucideIcon;
  priority?: boolean;
}

function maybeNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function toNumber(value: unknown): number {
  return maybeNumber(value) ?? 0;
}

function toDate(ts?: string): Date | null {
  if (!ts) return null;
  if (ts.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(ts)) return new Date(ts);
  return new Date(`${ts.replace(" ", "T")}Z`);
}

function formatTokens(value: number): string {
  return TOKEN_FORMATTER.format(value);
}

function formatMaybeTime(value?: string): string {
  const parsed = toDate(value);
  if (!parsed || Number.isNaN(parsed.getTime())) return "No activity";
  return TIME_FORMATTER.format(parsed);
}

function normalizeText(value?: string | null): string {
  return (value ?? "").trim().toLowerCase();
}

function getAgentDownloads(agent: RegistryItem): number {
  return toNumber(agent.download_count);
}

function getAgentRating(agent: RegistryItem): number | null {
  const rating = toNumber(agent.average_rating);
  return rating > 0 ? rating : null;
}

function getAgentStatus(agent: RegistryItem): string {
  return typeof agent.status === "string" ? agent.status : "";
}

function getAgentOwner(agent: RegistryItem): string {
  return typeof agent.owner === "string" ? agent.owner : "";
}

function isApproved(agent: RegistryItem): boolean {
  const status = getAgentStatus(agent);
  return !status || status === "approved";
}

function sessionPlatform(session: Session): string {
  return session.platform || session.service_name || "Unknown IDE";
}

function sessionAgentLabel(session: Session): string | null {
  return session.agent_name || session.agent_id || null;
}

function sessionTitle(session: Session): string {
  const prompts = toNumber(session.prompt_count);
  const promptLabel = prompts === 1 ? "prompt" : "prompts";
  const agent = session.agent_name ? `${session.agent_name} · ` : "";
  return `${agent}${prompts} ${promptLabel}`;
}

function computeTodayStats(sessions: Session[]) {
  const totals = sessions.reduce(
    (acc, session) => {
      const inputTokens = maybeNumber(session.total_input_tokens);
      const outputTokens = maybeNumber(session.total_output_tokens);
      acc.input += inputTokens ?? 0;
      acc.output += outputTokens ?? 0;
      acc.hasTokenData ||= inputTokens != null || outputTokens != null;
      acc.tools += toNumber(session.tool_result_count);
      acc.prompts += toNumber(session.prompt_count);
      if (session.is_active) acc.active += 1;

      const agent = sessionAgentLabel(session);
      if (agent) acc.agents.add(agent);

      const platform = sessionPlatform(session);
      if (platform) acc.platforms.add(platform);

      return acc;
    },
    {
      input: 0,
      output: 0,
      tools: 0,
      prompts: 0,
      active: 0,
      agents: new Set<string>(),
      platforms: new Set<string>(),
      hasTokenData: false,
    },
  );

  return {
    sessions: sessions.length,
    active: totals.active,
    prompts: totals.prompts,
    input: totals.input,
    output: totals.output,
    totalTokens: totals.input + totals.output,
    hasTokenData: totals.hasTokenData,
    tools: totals.tools,
    agentCount: totals.agents.size,
    platformCount: totals.platforms.size,
    platforms: Array.from(totals.platforms),
  };
}

function rankForUser(
  leaderboard: LeaderboardItem[] | undefined,
  email?: string,
  username?: string | null,
  name?: string,
): { item: LeaderboardItem; rank: number } | null {
  const emailKey = normalizeText(email);
  const usernameKey = normalizeText(username);
  const nameKey = normalizeText(name);

  const index = (leaderboard ?? []).findIndex((item) => {
    const itemEmail = normalizeText(item.created_by_email);
    const itemUsername = normalizeText(item.created_by_username);
    const itemOwner = normalizeText(item.owner);
    return (
      (emailKey && itemEmail === emailKey) ||
      (usernameKey && itemUsername === usernameKey) ||
      (nameKey && itemOwner === nameKey)
    );
  });

  if (index === -1 || !leaderboard) return null;
  return { item: leaderboard[index], rank: index + 1 };
}

function BriefMetric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 truncate font-mono text-xl font-semibold tracking-tight text-foreground">{value}</p>
      {detail && <p className="mt-1 truncate text-xs text-muted-foreground">{detail}</p>}
    </div>
  );
}

function SectionHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {description && <p className="mt-1 text-xs text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  );
}

function ActionRow({ action }: { action: HomeAction }) {
  const Icon = action.icon;
  return (
    <Link
      to={action.href}
      className="group flex items-center gap-3 rounded-md px-3 py-2.5 transition-colors hover:bg-accent/40"
    >
      <span className={action.priority ? "text-primary" : "text-muted-foreground"}>
        <Icon className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground">{action.title}</span>
        <span className="block truncate text-xs text-muted-foreground">{action.description}</span>
      </span>
      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
    </Link>
  );
}

function AgentImpactRow({ agent, index }: { agent: RegistryItem; index: number }) {
  const rating = getAgentRating(agent);
  return (
    <Link
      to="/agents/$agentId"
      params={{ agentId: agent.id }}
      className="grid grid-cols-[2rem_minmax(0,1fr)_5rem_4rem] items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors hover:bg-accent/40"
    >
      <span className="text-right font-mono text-xs font-medium text-muted-foreground">{index + 1}</span>
      <div className="min-w-0">
        <span className="block truncate font-medium text-foreground">{agent.name}</span>
        <span className="block truncate text-xs text-muted-foreground">{getAgentOwner(agent) || "Owned agent"}</span>
      </div>
      <span className="inline-flex items-center justify-end gap-1 font-mono text-xs text-muted-foreground">
        <ArrowDownToLine className="h-3 w-3" />
        {compactNumber(getAgentDownloads(agent))}
      </span>
      <span className="inline-flex items-center justify-end gap-1 text-xs text-muted-foreground">
        {rating ? (
          <>
            <Star className="h-3 w-3" />
            {rating.toFixed(1)}
          </>
        ) : (
          "None"
        )}
      </span>
    </Link>
  );
}

function SessionRow({ session, showTokens }: { session: Session; showTokens: boolean }) {
  return (
    <Link
      to="/traces/$traceId"
      params={{ traceId: session.session_id }}
      className={`grid ${showTokens ? "grid-cols-[minmax(0,1fr)_4.5rem_5rem]" : "grid-cols-[minmax(0,1fr)_5rem]"} items-center gap-3 rounded-md px-3 py-2.5 transition-colors hover:bg-accent/40`}
    >
      <div className="min-w-0">
        <span className="block truncate text-sm font-medium text-foreground">{sessionTitle(session)}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {sessionPlatform(session)} · {session.model || "Unknown model"}
        </span>
      </div>
      {showTokens && (
        <span className="text-right font-mono text-xs text-muted-foreground">
          {formatTokens(toNumber(session.total_input_tokens) + toNumber(session.total_output_tokens))}
        </span>
      )}
      <span className="text-right text-xs text-muted-foreground">{formatMaybeTime(session.last_event_time)}</span>
    </Link>
  );
}

function RankSummary({
  rank,
  isLoading,
}: {
  rank: { item: LeaderboardItem; rank: number } | null;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <div className="h-20 animate-pulse rounded-md bg-muted/40" />;
  }

  if (!rank) {
    return (
      <div className="rounded-md bg-muted/35 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
          <Medal className="h-4 w-4 text-muted-foreground" />
          Not ranked this week
        </div>
        <p className="mt-1 text-xs text-muted-foreground">Your agents are not in the top 50 for 7 day installs yet.</p>
      </div>
    );
  }

  return (
    <Link
      to="/agents/$agentId"
      params={{ agentId: rank.item.id }}
      className="flex items-center justify-between gap-4 rounded-md bg-primary/5 px-4 py-3 transition-colors hover:bg-primary/10"
    >
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">Best 7 day rank</p>
        <p className="mt-1 truncate text-sm font-medium text-foreground">{rank.item.name}</p>
      </div>
      <div className="text-right">
        <p className="font-mono text-3xl font-semibold tracking-tight text-foreground">#{rank.rank}</p>
        <p className="mt-1 text-xs text-muted-foreground">{compactNumber(rank.item.download_count)} installs</p>
      </div>
    </Link>
  );
}

export default function RegistryHome() {
  const [search, setSearch] = useState("");
  const router = useRouter();
  const { data: whoami } = useWhoami();
  const { data: sessionsToday, isLoading: sessionsLoading } = useSessions2({
    days: 1,
    limit: 200,
    mine: true,
    refetchInterval: 30_000,
  });
  const { data: myAgents, isLoading: myAgentsLoading } = useMyAgents();
  const { data: leaderboard, isLoading: leaderboardLoading } = useLeaderboard("7d", 50);
  const { data: topAgents, isLoading: topLoading } = useTopAgents(6);
  const {
    data: agents,
    isLoading: agentsLoading,
    isError: agentsError,
    error: agentsErr,
    refetch: refetchAgents,
  } = useRegistryList("agents");
  const { brandingAppName } = useDeploymentConfig();

  const todayStats = useMemo(() => computeTodayStats(sessionsToday ?? []), [sessionsToday]);
  const bestRank = useMemo(
    () => rankForUser(leaderboard, whoami?.email, whoami?.username, whoami?.name),
    [leaderboard, whoami?.email, whoami?.name, whoami?.username],
  );

  const approvedAgents = useMemo(() => (myAgents ?? []).filter(isApproved), [myAgents]);
  const draftAgents = useMemo(
    () => (myAgents ?? []).filter((agent) => ["draft", "pending", "rejected"].includes(getAgentStatus(agent))),
    [myAgents],
  );
  const ownedInstallTotal = useMemo(
    () => (myAgents ?? []).reduce((total, agent) => total + getAgentDownloads(agent), 0),
    [myAgents],
  );
  const averageRating = useMemo(() => {
    const ratings = (myAgents ?? []).map(getAgentRating).filter((rating): rating is number => rating != null);
    if (ratings.length === 0) return null;
    return ratings.reduce((total, rating) => total + rating, 0) / ratings.length;
  }, [myAgents]);
  const topOwnedAgents = useMemo(
    () => [...(myAgents ?? [])].sort((a, b) => getAgentDownloads(b) - getAgentDownloads(a)).slice(0, 5),
    [myAgents],
  );

  const recentSessions = (sessionsToday ?? []).slice(0, 5);
  const trending = (topAgents ?? []).slice(0, 4);
  const recentlyAdded = useMemo(
    () =>
      [...(agents ?? [])]
        .sort((a: RegistryItem, b: RegistryItem) => {
          const da = a.created_at ? new Date(a.created_at).getTime() : 0;
          const db = b.created_at ? new Date(b.created_at).getTime() : 0;
          return db - da;
        })
        .slice(0, 4),
    [agents],
  );

  const actions = useMemo<HomeAction[]>(() => {
    const items: HomeAction[] = [];
    const latestSession = recentSessions[0];
    if (latestSession) {
      items.push({
        title: "Resume last trace",
        description: `${sessionPlatform(latestSession)} at ${formatMaybeTime(latestSession.last_event_time)}`,
        href: `/traces/${latestSession.session_id}`,
        icon: Activity,
        priority: true,
      });
    } else {
      items.push({
        title: "Start capturing sessions",
        description: "Patch your IDE and send your first coding trace into Observal.",
        href: "/wiki",
        icon: Terminal,
        priority: true,
      });
    }

    if (draftAgents.length > 0) {
      items.push({
        title: `Finish ${draftAgents.length} draft${draftAgents.length === 1 ? "" : "s"}`,
        description: "Complete and submit unfinished agents for review.",
        href: "/agents",
        icon: FileEdit,
      });
    } else {
      items.push({
        title: "Build an agent",
        description: "Bundle prompts, skills, MCPs, hooks, and sandboxes.",
        href: "/agents/builder",
        icon: WandSparkles,
      });
    }

    items.push({
      title: "Browse agents",
      description: "Find a ready-made agent and pull it into your IDE.",
      href: "/agents",
      icon: Bot,
    });

    return items;
  }, [draftAgents.length, recentSessions]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (search.trim()) {
      router.navigate({ to: "/agents", search: { search: search.trim() } });
    }
  }

  const displayName = whoami?.name || whoami?.username || whoami?.email || "there";
  const primarySummary = sessionsLoading
    ? "Loading today's activity"
    : todayStats.sessions > 0 && todayStats.hasTokenData
      ? `${todayStats.sessions} session${todayStats.sessions === 1 ? "" : "s"} today using ${formatTokens(todayStats.totalTokens)} tokens.`
      : todayStats.sessions > 0
        ? `${todayStats.sessions} session${todayStats.sessions === 1 ? "" : "s"} captured today.`
        : "No coding sessions captured today.";

  return (
    <>
      <PageHeader title="Home" breadcrumbs={[{ label: "Registry" }]} />

      <div className="w-full space-y-8 p-6 lg:p-8">
        <section className="animate-in space-y-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl space-y-3">
              <div className="space-y-2">
                <h1 className="text-2xl font-display font-semibold tracking-tight text-foreground sm:text-3xl">
                  {displayName}, here is your day in {brandingAppName || "Observal"}.
                </h1>
                <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                  {primarySummary} Track coding activity, registry impact, and the next useful move.
                </p>
              </div>
            </div>
            <form onSubmit={handleSearch} className="relative w-full max-w-md">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search agents by name, owner, or description..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-10 pl-9"
              />
            </form>
          </div>

          <div className="rounded-md border border-border bg-card">
            <div className="grid gap-6 px-4 py-4 md:grid-cols-3 xl:grid-cols-6">
              <BriefMetric
                label="Sessions today"
                value={sessionsLoading ? "..." : formatNumber(todayStats.sessions)}
                detail={todayStats.active > 0 ? `${todayStats.active} active now` : `${todayStats.prompts} prompts`}
              />
              {(sessionsLoading || todayStats.hasTokenData) && (
                <BriefMetric
                  label="Tokens"
                  value={sessionsLoading ? "..." : formatTokens(todayStats.totalTokens)}
                  detail={todayStats.hasTokenData ? `${formatTokens(todayStats.input)} in · ${formatTokens(todayStats.output)} out` : undefined}
                />
              )}
              <BriefMetric
                label="Tool calls"
                value={sessionsLoading ? "..." : formatNumber(todayStats.tools)}
                detail={`${todayStats.agentCount} agents · ${todayStats.platformCount} IDEs`}
              />
              <BriefMetric
                label="Best rank"
                value={leaderboardLoading ? "..." : bestRank ? `#${bestRank.rank}` : "Unranked"}
                detail={bestRank ? bestRank.item.name : "7 day board"}
              />
              <BriefMetric
                label="Owned installs"
                value={myAgentsLoading ? "..." : compactNumber(ownedInstallTotal)}
                detail={`${approvedAgents.length} published agents`}
              />
              <BriefMetric
                label="Avg rating"
                value={myAgentsLoading ? "..." : averageRating ? averageRating.toFixed(1) : "New"}
                detail={draftAgents.length > 0 ? `${draftAgents.length} drafts or pending` : "No drafts waiting"}
              />
            </div>
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,420px)]">
          <div className="rounded-md border border-border bg-card">
            <SectionHeader
              title="Coding activity today"
              description="Input, output, tools, and recent sessions from your IDEs."
              action={
                <Button asChild variant="outline" size="sm">
                  <Link to="/traces">View traces</Link>
                </Button>
              }
            />

            {(sessionsLoading || todayStats.hasTokenData || todayStats.platforms.length > 0) && (
              <div className={`grid border-b border-border ${sessionsLoading || todayStats.hasTokenData ? "md:grid-cols-3" : "md:grid-cols-1"}`}>
                {(sessionsLoading || todayStats.hasTokenData) && (
                  <>
                    <div className="border-b border-border px-4 py-3 md:border-b-0 md:border-r">
                      <p className="text-xs text-muted-foreground">Input tokens</p>
                      <p className="mt-2 font-mono text-xl font-semibold text-foreground">
                        {sessionsLoading ? "..." : formatTokens(todayStats.input)}
                      </p>
                    </div>
                    <div className="border-b border-border px-4 py-3 md:border-b-0 md:border-r">
                      <p className="text-xs text-muted-foreground">Output tokens</p>
                      <p className="mt-2 font-mono text-xl font-semibold text-foreground">
                        {sessionsLoading ? "..." : formatTokens(todayStats.output)}
                      </p>
                    </div>
                  </>
                )}
                <div className="px-4 py-3">
                  <p className="text-xs text-muted-foreground">Platforms</p>
                  <p className="mt-2 truncate text-sm font-medium text-foreground">
                    {todayStats.platforms.length > 0 ? todayStats.platforms.slice(0, 3).join(", ") : "No IDE activity"}
                  </p>
                </div>
              </div>
            )}

            <div className="p-2">
              {sessionsLoading ? (
                <TableSkeleton rows={5} cols={3} />
              ) : recentSessions.length === 0 ? (
                <div className="p-6">
                  <EmptyState
                    icon={Activity}
                    title="No sessions today"
                    description="Run a coding session with Observal telemetry enabled to see tokens, tools, and traces here."
                    actionLabel="Open setup docs"
                    actionHref="/wiki"
                  />
                </div>
              ) : (
                <div className="space-y-1">
                  <div className={`grid ${todayStats.hasTokenData ? "grid-cols-[minmax(0,1fr)_4.5rem_5rem]" : "grid-cols-[minmax(0,1fr)_5rem]"} gap-3 px-3 py-2 text-xs font-medium text-muted-foreground`}>
                    <span>Session</span>
                    {todayStats.hasTokenData && <span className="text-right">Tokens</span>}
                    <span className="text-right">Latest</span>
                  </div>
                  {recentSessions.map((session) => (
                    <SessionRow key={session.session_id} session={session} showTokens={todayStats.hasTokenData} />
                  ))}
                </div>
              )}
            </div>
          </div>

          <aside className="rounded-md border border-border bg-card">
            <SectionHeader title="Registry impact" description="Rank, owned agents, and immediate follow-ups." />
            <div className="space-y-4 p-4">
              <RankSummary rank={bestRank} isLoading={leaderboardLoading} />

              <div>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <h3 className="text-xs font-medium text-muted-foreground">Your agents</h3>
                  <Link to="/agents" className="text-xs text-muted-foreground hover:text-foreground">
                    Manage
                  </Link>
                </div>
                {myAgentsLoading ? (
                  <TableSkeleton rows={3} cols={3} />
                ) : topOwnedAgents.length === 0 ? (
                  <EmptyState
                    icon={Bot}
                    title="No agents owned yet"
                    description="Create your first reusable coding agent and track installs here."
                    actionLabel="Open builder"
                    actionHref="/agents/builder"
                  />
                ) : (
                  <div className="space-y-1">
                    {topOwnedAgents.map((agent, index) => (
                      <AgentImpactRow key={agent.id} agent={agent} index={index} />
                    ))}
                  </div>
                )}
              </div>

              <div>
                <h3 className="mb-2 text-xs font-medium text-muted-foreground">Next up</h3>
                <div className="space-y-1">
                  {actions.map((action) => (
                    <ActionRow key={action.title} action={action} />
                  ))}
                </div>
              </div>
            </div>
          </aside>
        </section>

        <section className="grid gap-6 xl:grid-cols-2">
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-sm font-semibold text-foreground">Trending agents</h2>
              </div>
              <Link to="/leaderboard" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                View rankings <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            {topLoading ? (
              <CardSkeleton count={4} columns={4} />
            ) : trending.length === 0 ? (
              <EmptyState
                icon={CircleAlert}
                title="No trending agents yet"
                description="Agents with recent installs will appear here after your team starts pulling them."
              />
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                {trending.map((item: TopAgentItem) => (
                  <AgentCard
                    key={item.id}
                    id={item.id}
                    name={item.name}
                    downloads={item.download_count}
                    score={item.average_rating ?? undefined}
                    description={item.description}
                    owner={item.owner}
                    version={item.version}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Clock3 className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-sm font-semibold text-foreground">Recently added</h2>
              </div>
              <Link to="/agents" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                Browse agents <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            {agentsLoading ? (
              <CardSkeleton count={4} columns={4} />
            ) : agentsError ? (
              <ErrorState message={agentsErr?.message} onRetry={() => refetchAgents()} />
            ) : recentlyAdded.length === 0 ? (
              <EmptyState
                icon={Bot}
                title="No agents yet"
                description="Published agents will appear here once your registry has content."
                actionLabel="Create an agent"
                actionHref="/agents/builder"
              />
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                {recentlyAdded.map((agent: RegistryItem) => (
                  <AgentCard
                    key={agent.id}
                    id={agent.id}
                    name={agent.name}
                    description={agent.description as string | undefined}
                    owner={agent.owner as string | undefined}
                    version={agent.version as string | undefined}
                    downloads={agent.download_count as number | undefined}
                    score={(agent.average_rating as number | null) ?? undefined}
                    component_count={agent.component_count as number | undefined}
                  />
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
