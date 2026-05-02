"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Trophy,
  ArrowDownToLine,
  Star,
  Search,
  Blocks,
  Users,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { EmptyState } from "@/components/shared/empty-state";
import { useLeaderboard, useComponentLeaderboard } from "@/hooks/use-api";
import { compactNumber } from "@/lib/utils";
import type { LeaderboardWindow } from "@/lib/types";

type TopTab = "agents" | "components";
type SubTab = "leaderboard" | "users";

interface UserAggregate {
  email: string;
  username?: string | null;
  totalDownloads: number;
  itemCount: number;
}

export default function LeaderboardPage() {
  const [topTab, setTopTab] = useState<TopTab>("agents");
  const [agentSubTab, setAgentSubTab] = useState<SubTab>("leaderboard");
  const [componentSubTab, setComponentSubTab] = useState<SubTab>("leaderboard");
  const [window, setWindow] = useState<LeaderboardWindow>("7d");
  const [userFilterInput, setUserFilterInput] = useState("");
  const [userFilter, setUserFilter] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setUserFilter(userFilterInput), 300);
    return () => clearTimeout(timer);
  }, [userFilterInput]);

  const { data: leaderboard, isLoading: agentsLoading } = useLeaderboard(
    window,
    50,
    userFilter || undefined,
  );
  const { data: componentLeaderboard, isLoading: componentsLoading } =
    useComponentLeaderboard(window, 50);

  const rankedComponents = useMemo(
    () =>
      componentLeaderboard
        ? [...componentLeaderboard].sort((a, b) => b.download_count - a.download_count)
        : [],
    [componentLeaderboard],
  );

  const agentUserAggregates = useMemo<UserAggregate[]>(() => {
    if (!leaderboard) return [];
    const map = new Map<string, UserAggregate>();
    for (const item of leaderboard) {
      const email = item.created_by_email || item.owner || "unknown";
      const existing = map.get(email);
      if (existing) {
        existing.totalDownloads += item.download_count;
        existing.itemCount += 1;
      } else {
        map.set(email, {
          email,
          username: item.created_by_username,
          totalDownloads: item.download_count,
          itemCount: 1,
        });
      }
    }
    return [...map.values()].sort((a, b) => b.totalDownloads - a.totalDownloads);
  }, [leaderboard]);

  const componentUserAggregates = useMemo<UserAggregate[]>(() => {
    if (!componentLeaderboard) return [];
    const map = new Map<string, UserAggregate>();
    for (const item of componentLeaderboard) {
      const email = item.created_by_email || "unknown";
      const existing = map.get(email);
      if (existing) {
        existing.totalDownloads += item.download_count;
        existing.itemCount += 1;
      } else {
        map.set(email, {
          email,
          totalDownloads: item.download_count,
          itemCount: 1,
        });
      }
    }
    return [...map.values()].sort((a, b) => b.totalDownloads - a.totalDownloads);
  }, [componentLeaderboard]);

  return (
    <>
      <PageHeader
        title="Leaderboard"
        breadcrumbs={[
          { label: "Registry", href: "/" },
          { label: "Leaderboard" },
        ]}
      />

      <div className="p-6 lg:p-8 w-full mx-auto space-y-6">
        <Tabs
          value={topTab}
          onValueChange={(v) => setTopTab(v as TopTab)}
        >
          <div className="flex items-center justify-between flex-wrap gap-4">
            <TabsList>
              <TabsTrigger value="agents">Agents</TabsTrigger>
              <TabsTrigger value="components">Components</TabsTrigger>
            </TabsList>

            <Tabs
              value={window}
              onValueChange={(v) => setWindow(v as LeaderboardWindow)}
            >
              <TabsList>
                <TabsTrigger value="24h">24h</TabsTrigger>
                <TabsTrigger value="7d">7 days</TabsTrigger>
                <TabsTrigger value="30d">30 days</TabsTrigger>
                <TabsTrigger value="all">All time</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          {/* ── Agents tab ───────────────────────────────────── */}
          <TabsContent value="agents">
            <Tabs value={agentSubTab} onValueChange={(v) => setAgentSubTab(v as SubTab)}>
              <div className="flex items-center justify-between flex-wrap gap-4 mb-4">
                <TabsList>
                  <TabsTrigger value="leaderboard">
                    <Trophy className="h-3.5 w-3.5 mr-1.5" />
                    Leaderboard
                  </TabsTrigger>
                  <TabsTrigger value="users">
                    <Users className="h-3.5 w-3.5 mr-1.5" />
                    Users
                  </TabsTrigger>
                </TabsList>
                <div className="relative w-full sm:w-72">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Filter by email or username..."
                    value={userFilterInput}
                    onChange={(e) => setUserFilterInput(e.target.value)}
                    className="pl-9 h-9"
                  />
                </div>
              </div>

              <TabsContent value="leaderboard">
                {agentsLoading ? (
                  <TableSkeleton rows={10} cols={5} />
                ) : !leaderboard || leaderboard.length === 0 ? (
                  <EmptyState
                    icon={Trophy}
                    title="No rankings yet"
                    description="Install agents via the CLI or web UI to populate the leaderboard."
                  />
                ) : (
                  <div className="space-y-1 animate-in">
                    <div className="flex items-center gap-4 px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      <span className="w-8 text-right">#</span>
                      <span className="flex-1">Agent</span>
                      <span className="w-24 text-right">Downloads</span>
                      <span className="w-16 text-right">Rating</span>
                      <span className="w-20 text-right">Version</span>
                    </div>

                    {leaderboard.map((item, i) => (
                      <Link
                        key={item.id}
                        href={`/agents/${item.id}`}
                        className="flex items-center gap-4 rounded-md px-3 py-3 transition-colors hover:bg-accent/40 group"
                      >
                        <span className={`w-8 text-right font-mono font-semibold ${i < 3 ? "text-foreground" : "text-muted-foreground"}`}>
                          {i + 1}
                        </span>
                        <div className="flex-1 min-w-0">
                          <span className="text-sm font-medium truncate block group-hover:underline underline-offset-4">
                            {item.name}
                          </span>
                          <span className="text-xs text-muted-foreground/70 truncate block">
                            {item.created_by_username ? `@${item.created_by_username}` : item.owner}
                            {item.description && ` — ${item.description}`}
                          </span>
                        </div>
                        <span className="w-24 text-right inline-flex items-center justify-end gap-1 text-sm text-muted-foreground font-mono">
                          <ArrowDownToLine className="h-3 w-3" />
                          {compactNumber(item.download_count)}
                        </span>
                        <span className="w-16 text-right inline-flex items-center justify-end gap-1 text-sm text-muted-foreground">
                          {item.average_rating != null ? (
                            <>
                              <Star className="h-3 w-3" />
                              {item.average_rating.toFixed(1)}
                            </>
                          ) : (
                            "-"
                          )}
                        </span>
                        <span className="w-20 text-right">
                          {item.version ? (
                            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                              {item.version}
                            </Badge>
                          ) : (
                            <span className="text-sm text-muted-foreground">-</span>
                          )}
                        </span>
                      </Link>
                    ))}
                  </div>
                )}
              </TabsContent>

              <TabsContent value="users">
                {agentsLoading ? (
                  <TableSkeleton rows={10} cols={4} />
                ) : agentUserAggregates.length === 0 ? (
                  <EmptyState
                    icon={Users}
                    title="No user data yet"
                    description="User download totals will appear once agents are installed."
                  />
                ) : (
                  <div className="space-y-1 animate-in">
                    <div className="flex items-center gap-4 px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      <span className="w-8 text-right">#</span>
                      <span className="flex-1">User</span>
                      <span className="w-24 text-right">Agents</span>
                      <span className="w-28 text-right">Total Downloads</span>
                    </div>

                    {agentUserAggregates.map((user, i) => (
                      <div
                        key={user.email}
                        className="flex items-center gap-4 rounded-md px-3 py-3 transition-colors hover:bg-accent/40"
                      >
                        <span className={`w-8 text-right font-mono font-semibold ${i < 3 ? "text-foreground" : "text-muted-foreground"}`}>
                          {i + 1}
                        </span>
                        <div className="flex-1 min-w-0">
                          <span className="text-sm font-medium truncate block">
                            {user.username ? `@${user.username}` : user.email}
                          </span>
                          {user.username && (
                            <span className="text-xs text-muted-foreground/70 truncate block">
                              {user.email}
                            </span>
                          )}
                        </div>
                        <span className="w-24 text-right text-sm text-muted-foreground font-mono">
                          {user.itemCount}
                        </span>
                        <span className="w-28 text-right inline-flex items-center justify-end gap-1 text-sm text-muted-foreground font-mono">
                          <ArrowDownToLine className="h-3 w-3" />
                          {compactNumber(user.totalDownloads)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </TabsContent>

          {/* ── Components tab ────────────────────────────────── */}
          <TabsContent value="components">
            <Tabs value={componentSubTab} onValueChange={(v) => setComponentSubTab(v as SubTab)}>
              <div className="flex items-center justify-between flex-wrap gap-4 mb-4">
                <TabsList>
                  <TabsTrigger value="leaderboard">
                    <Blocks className="h-3.5 w-3.5 mr-1.5" />
                    Leaderboard
                  </TabsTrigger>
                  <TabsTrigger value="users">
                    <Users className="h-3.5 w-3.5 mr-1.5" />
                    Users
                  </TabsTrigger>
                </TabsList>
              </div>

              <TabsContent value="leaderboard">
                {componentsLoading ? (
                  <TableSkeleton rows={10} cols={4} />
                ) : rankedComponents.length === 0 ? (
                  <EmptyState
                    icon={Blocks}
                    title="No component data yet"
                    description="Component download metrics will appear here once users install components."
                  />
                ) : (
                  <div className="space-y-1 animate-in">
                    <div className="flex items-center gap-4 px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      <span className="w-8 text-right">#</span>
                      <span className="flex-1">Component</span>
                      <span className="w-20 text-right">Type</span>
                      <span className="w-20 text-right">Rating</span>
                      <span className="w-28 text-right">Downloads</span>
                    </div>

                    {rankedComponents.map((item, i) => (
                      <div
                        key={item.id}
                        className="flex items-center gap-4 rounded-md px-3 py-3 transition-colors hover:bg-accent/40"
                      >
                        <span className={`w-8 text-right font-mono font-semibold ${i < 3 ? "text-foreground" : "text-muted-foreground"}`}>
                          {i + 1}
                        </span>
                        <div className="flex-1 min-w-0">
                          <span className="text-sm font-medium truncate block">
                            {item.name}
                          </span>
                          <span className="text-xs text-muted-foreground/70 truncate block">
                            {item.created_by_email}
                            {item.description && ` — ${item.description}`}
                          </span>
                        </div>
                        <span className="w-20 text-right">
                          <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                            {item.component_type}
                          </Badge>
                        </span>
                        <span className="w-20 text-right inline-flex items-center justify-end gap-1 text-sm text-muted-foreground">
                          {item.average_rating != null ? (
                            <>
                              <Star className="h-3 w-3 fill-amber-500 text-amber-500" />
                              {item.average_rating.toFixed(1)}
                            </>
                          ) : (
                            <span className="text-muted-foreground/40">-</span>
                          )}
                        </span>
                        <span className="w-28 text-right inline-flex items-center justify-end gap-1 text-sm text-muted-foreground font-mono">
                          <ArrowDownToLine className="h-3 w-3" />
                          {compactNumber(item.download_count)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>

              <TabsContent value="users">
                {componentsLoading ? (
                  <TableSkeleton rows={10} cols={4} />
                ) : componentUserAggregates.length === 0 ? (
                  <EmptyState
                    icon={Users}
                    title="No user data yet"
                    description="User download totals will appear once components are installed."
                  />
                ) : (
                  <div className="space-y-1 animate-in">
                    <div className="flex items-center gap-4 px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      <span className="w-8 text-right">#</span>
                      <span className="flex-1">User</span>
                      <span className="w-24 text-right">Components</span>
                      <span className="w-28 text-right">Total Downloads</span>
                    </div>

                    {componentUserAggregates.map((user, i) => (
                      <div
                        key={user.email}
                        className="flex items-center gap-4 rounded-md px-3 py-3 transition-colors hover:bg-accent/40"
                      >
                        <span className={`w-8 text-right font-mono font-semibold ${i < 3 ? "text-foreground" : "text-muted-foreground"}`}>
                          {i + 1}
                        </span>
                        <div className="flex-1 min-w-0">
                          <span className="text-sm font-medium truncate block">
                            {user.email}
                          </span>
                        </div>
                        <span className="w-24 text-right text-sm text-muted-foreground font-mono">
                          {user.itemCount}
                        </span>
                        <span className="w-28 text-right inline-flex items-center justify-end gap-1 text-sm text-muted-foreground font-mono">
                          <ArrowDownToLine className="h-3 w-3" />
                          {compactNumber(user.totalDownloads)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}
