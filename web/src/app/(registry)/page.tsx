"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import {
  Search,
  TrendingUp,
  Clock,
  Check,
  Copy,
  Terminal,
  Trophy,
  ArrowRight,
  ArrowDownToLine,
  Star,
} from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AgentCard } from "@/components/registry/agent-card";
import {
  useRegistryList,
  useTopAgents,
  useOverviewStats,
  useLeaderboard,
} from "@/hooks/use-api";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/layouts/page-header";
import { CardSkeleton, TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { compactNumber } from "@/lib/utils";
import type { LeaderboardWindow, TopAgentItem, RegistryItem } from "@/lib/types";

export default function RegistryHome() {
  const [search, setSearch] = useState("");
  const [heroCopied, setHeroCopied] = useState(false);
  const [leaderboardWindow, setLeaderboardWindow] =
    useState<LeaderboardWindow>("7d");
  const router = useRouter();
  const {
    data: agents,
    isLoading: agentsLoading,
    isError: agentsError,
    error: agentsErr,
    refetch: refetchAgents,
  } = useRegistryList("agents");
  const { data: topAgents, isLoading: topLoading } = useTopAgents();
  const { data: stats } = useOverviewStats();
  const { data: leaderboard, isLoading: leaderboardLoading } =
    useLeaderboard(leaderboardWindow, 10);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (search.trim()) {
      router.push(`/agents?search=${encodeURIComponent(search.trim())}`);
    }
  }

  const handleHeroCopy = useCallback(() => {
    navigator.clipboard.writeText("observal pull my-agent --ide cursor");
    setHeroCopied(true);
    toast.success("Copied to clipboard");
    setTimeout(() => setHeroCopied(false), 2000);
  }, []);

  const trending = (topAgents ?? []).slice(0, 6);
  const recentlyAdded = (agents ?? [])
    .sort((a: RegistryItem, b: RegistryItem) => {
      const da = a.created_at ? new Date(a.created_at).getTime() : 0;
      const db = b.created_at ? new Date(b.created_at).getTime() : 0;
      return db - da;
    })
    .slice(0, 6);

  return (
    <>
      <PageHeader
        title="Agent Registry"
        breadcrumbs={[{ label: "Registry" }]}
      />

      <div className="p-6 lg:p-8 w-full max-w-[1200px] mx-auto space-y-12">
        {/* Hero section */}
        <section className="animate-in space-y-6 pt-2">
          <div className="space-y-3 max-w-2xl">
            <h1 className="text-2xl sm:text-3xl font-display font-bold tracking-tight text-foreground">
              Observal
            </h1>
            <p className="text-base text-muted-foreground leading-relaxed max-w-lg">
              The open registry for AI agents. Browse, install, and evaluate
              agents across your team.
            </p>
          </div>

          {/* Stats bar */}
          {stats && (
            <div className="flex items-center gap-6 text-sm text-muted-foreground">
              <span className="font-mono font-medium text-foreground">
                {stats.total_agents}
              </span>{" "}
              agents
              <span className="text-border">·</span>
              <span className="font-mono font-medium text-foreground">
                {stats.total_mcps}
              </span>{" "}
              components
              <span className="text-border">·</span>
              <span className="font-mono font-medium text-foreground">
                {stats.total_users}
              </span>{" "}
              engineers
            </div>
          )}

          {/* Search bar */}
          <form onSubmit={handleSearch} className="relative max-w-lg">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search agents by name, owner, or description..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-10"
            />
          </form>

          {/* Terminal snippet */}
          <div className="max-w-lg">
            <div className="flex items-center gap-2 rounded-md border border-border bg-surface-sunken px-3 py-2.5">
              <Terminal className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <code className="flex-1 text-sm font-mono text-foreground select-all">
                <span className="text-muted-foreground">$</span>{" "}
                observal pull my-agent --ide cursor
              </code>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={handleHeroCopy}
                aria-label="Copy command"
              >
                {heroCopied ? (
                  <Check className="h-3.5 w-3.5 text-success" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
              </Button>
            </div>
          </div>
        </section>

        {/* Trending Agents */}
        <section className="animate-in stagger-1 space-y-4">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold font-display uppercase tracking-wider text-muted-foreground">
              Trending
            </h2>
          </div>
          {topLoading ? (
            <CardSkeleton count={3} columns={3} />
          ) : trending.length === 0 ? (
            <EmptyState
              icon={TrendingUp}
              title="No trending agents"
              description="Agents with the most downloads will appear here."
            />
          ) : (
            <div
              className="grid gap-4"
              style={{
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(min(320px, 100%), 1fr))",
              }}
            >
              {trending.map((item: TopAgentItem, i: number) => (
                <AgentCard
                  key={item.id}
                  id={item.id}
                  name={item.name}
                  downloads={item.download_count}
                  score={item.average_rating ?? undefined}
                  description={item.description}
                  owner={item.owner}
                  version={item.version}
                  className={`animate-in stagger-${Math.min(i + 1, 5)}`}
                />
              ))}
            </div>
          )}
        </section>

        {/* Leaderboard */}
        <section className="animate-in stagger-2 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Trophy className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold font-display uppercase tracking-wider text-muted-foreground">
                Leaderboard
              </h2>
            </div>
            <Link
              href="/agents/leaderboard"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              View all <ArrowRight className="h-3 w-3" />
            </Link>
          </div>

          <Tabs
            value={leaderboardWindow}
            onValueChange={(v) =>
              setLeaderboardWindow(v as LeaderboardWindow)
            }
          >
            <TabsList>
              <TabsTrigger value="24h">24h</TabsTrigger>
              <TabsTrigger value="7d">7d</TabsTrigger>
              <TabsTrigger value="30d">30d</TabsTrigger>
              <TabsTrigger value="all">All time</TabsTrigger>
            </TabsList>
          </Tabs>

          {leaderboardLoading ? (
            <TableSkeleton rows={5} cols={4} />
          ) : !leaderboard || leaderboard.length === 0 ? (
            <EmptyState
              icon={Trophy}
              title="No leaderboard data"
              description="Install agents to see rankings appear here."
            />
          ) : (
            <div className="space-y-1">
              {leaderboard.map((item, i) => (
                <Link
                  key={item.id}
                  href={`/agents/${item.id}`}
                  className="flex items-center gap-4 rounded-md px-3 py-2.5 transition-colors hover:bg-accent/40"
                >
                  <span className="w-6 text-right text-sm font-mono font-medium text-muted-foreground">
                    {i + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium truncate block">
                      {item.name}
                    </span>
                    {item.owner && (
                      <span className="text-xs text-muted-foreground/70">
                        {item.owner}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 shrink-0 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <ArrowDownToLine className="h-3 w-3" />
                      {compactNumber(item.download_count)}
                    </span>
                    {item.average_rating != null && (
                      <span className="inline-flex items-center gap-1">
                        <Star className="h-3 w-3" />
                        {item.average_rating.toFixed(1)}
                      </span>
                    )}
                    {item.version && (
                      <Badge
                        variant="secondary"
                        className="text-[10px] px-1.5 py-0"
                      >
                        {item.version}
                      </Badge>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>

        {/* Recently Added */}
        <section className="animate-in stagger-3 space-y-4">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold font-display uppercase tracking-wider text-muted-foreground">
              Recently Added
            </h2>
          </div>
          {agentsLoading ? (
            <CardSkeleton count={3} columns={3} />
          ) : agentsError ? (
            <ErrorState
              message={agentsErr?.message}
              onRetry={() => refetchAgents()}
            />
          ) : recentlyAdded.length === 0 ? (
            <EmptyState
              icon={Clock}
              title="No agents yet"
              description="Agents will appear here once published. Submit your first agent to get started."
              actionLabel="Browse Agents"
              actionHref="/agents"
            />
          ) : (
            <div
              className="grid gap-4"
              style={{
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(min(320px, 100%), 1fr))",
              }}
            >
              {recentlyAdded.map((agent: RegistryItem, i: number) => (
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
                  className={`animate-in stagger-${Math.min(i + 1, 5)}`}
                />
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
