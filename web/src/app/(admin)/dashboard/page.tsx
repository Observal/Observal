"use client";

import Link from "next/link";
import { Bot, Activity, TrendingUp, TrendingDown, Minus, Download } from "lucide-react";
import { useOverviewStats, useRegistryList, useTopAgents, useOtelSessions } from "@/hooks/use-api";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/layouts/page-header";
import { CardSkeleton, TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

function TrendIcon({ value }: { value: number }) {
  if (value > 0) return <TrendingUp className="h-3 w-3 text-success" />;
  if (value < 0) return <TrendingDown className="h-3 w-3 text-destructive" />;
  return <Minus className="h-3 w-3 text-muted-foreground" />;
}

function StatIndicator({ label, value, trend = 0 }: { label: string; value: string | number; trend?: number }) {
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="text-xs text-muted-foreground whitespace-nowrap">{label}</span>
      <span className="text-sm font-semibold font-[family-name:var(--font-display)] tabular-nums">{value}</span>
      <span className="flex items-center gap-0.5">
        <TrendIcon value={trend} />
        {trend !== 0 && (
          <span className={`text-xs tabular-nums ${trend > 0 ? "text-success" : "text-destructive"}`}>
            {trend > 0 ? "+" : ""}{trend}%
          </span>
        )}
      </span>
    </div>
  );
}

function TopDownloadsBar({ items }: { items: { name: string; value: number }[] }) {
  const maxVal = Math.max(...items.map((i) => i.value), 1);

  return (
    <div className="space-y-1.5">
      {items.map((item) => (
        <div key={item.name} className="flex items-center gap-3 text-sm">
          <span className="font-[family-name:var(--font-display)] text-xs truncate min-w-0 flex-1">
            {item.name}
          </span>
          <div className="relative flex items-center justify-end w-24 h-5">
            <div
              className="absolute inset-y-0 right-0 bg-muted rounded-sm"
              style={{ width: `${(item.value / maxVal) * 100}%` }}
            />
            <span className="relative text-xs font-[family-name:var(--font-mono)] text-muted-foreground tabular-nums pr-1.5">
              {item.value.toLocaleString()}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const { data: stats, isLoading: statsLoading, isError: statsError, error: statsErr, refetch: refetchStats } = useOverviewStats();
  const { data: agents, isLoading: agentsLoading, isError: agentsError, error: agentsErr, refetch: refetchAgents } = useRegistryList("agents");
  const { data: topAgents } = useTopAgents();
  const { data: sessions, isLoading: sessionsLoading } = useOtelSessions();

  const recentSessions = (sessions ?? []).slice(0, 8);
  const totalDownloads = topAgents?.reduce((s: number, a: { download_count: number }) => s + a.download_count, 0) ?? 0;

  return (
    <>
      <PageHeader
        title="Dashboard"
        breadcrumbs={[
          { label: "Dashboard" },
        ]}
      />
      <div className="p-6 max-w-6xl mx-auto space-y-8">
        {/* Stats row */}
        {statsLoading ? (
          <CardSkeleton count={4} />
        ) : statsError ? (
          <ErrorState message={statsErr?.message} onRetry={() => refetchStats()} />
        ) : (
          <div className="animate-in flex flex-wrap items-center gap-x-6 gap-y-1 border-b border-border pb-6">
            <StatIndicator label="Agents" value={stats?.total_agents ?? 0} trend={12} />
            <StatIndicator label="Downloads" value={totalDownloads.toLocaleString()} trend={8} />
            <StatIndicator label="Users" value={stats?.total_users ?? 0} trend={0} />
            <StatIndicator label="Components" value={stats?.total_mcps ?? 0} trend={3} />
          </div>
        )}

        {/* Main content grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left column: 2/3 */}
          <div className="lg:col-span-2 space-y-6">
            {/* Recent Agents */}
            <section className="animate-in stagger-1">
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                Recent Agents
              </h3>
              {agentsLoading ? (
                <TableSkeleton rows={5} cols={4} />
              ) : agentsError ? (
                <ErrorState message={agentsErr?.message} onRetry={() => refetchAgents()} />
              ) : (agents ?? []).length === 0 ? (
                <EmptyState
                  icon={Bot}
                  title="No agents deployed"
                  description="Agents will appear here once they are submitted to the registry."
                  actionLabel="Browse Registry"
                  actionHref="/agents"
                />
              ) : (
                <div className="overflow-x-auto rounded-md border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="h-8 text-xs">Name</TableHead>
                        <TableHead className="h-8 text-xs">Version</TableHead>
                        <TableHead className="h-8 text-xs">Status</TableHead>
                        <TableHead className="h-8 text-xs text-right">Date</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(agents ?? []).slice(0, 10).map((a: any) => (
                        <TableRow key={a.id} className="group">
                          <TableCell className="py-1.5">
                            <Link
                              href={`/agents/${a.id}`}
                              className="font-[family-name:var(--font-display)] text-sm font-medium hover:text-primary-accent transition-colors"
                            >
                              {a.name}
                            </Link>
                          </TableCell>
                          <TableCell className="py-1.5 text-xs text-muted-foreground font-[family-name:var(--font-mono)]">
                            {a.version ?? "-"}
                          </TableCell>
                          <TableCell className="py-1.5">
                            <Badge
                              variant={a.status === "approved" ? "default" : "secondary"}
                              className="text-[10px] px-1.5 py-0"
                            >
                              {a.status}
                            </Badge>
                          </TableCell>
                          <TableCell className="py-1.5 text-xs text-muted-foreground text-right">
                            {a.created_at ? new Date(a.created_at).toLocaleDateString() : "-"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </section>

            {/* Latest Traces */}
            <section className="animate-in stagger-2">
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                Latest Traces
              </h3>
              {sessionsLoading ? (
                <TableSkeleton rows={5} cols={3} />
              ) : recentSessions.length === 0 ? (
                <EmptyState
                  icon={Activity}
                  title="No traces yet"
                  description="Traces will appear here once telemetry data is collected."
                />
              ) : (
                <div className="overflow-x-auto rounded-md border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="h-8 text-xs">Session ID</TableHead>
                        <TableHead className="h-8 text-xs">Service</TableHead>
                        <TableHead className="h-8 text-xs text-right">Time</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {recentSessions.map((s: any) => (
                        <TableRow key={s.session_id} className="group">
                          <TableCell className="py-1.5">
                            <Link
                              href={`/traces/${s.session_id}`}
                              className="font-[family-name:var(--font-mono)] text-xs hover:text-primary-accent transition-colors"
                            >
                              {s.session_id.slice(0, 12)}...
                            </Link>
                          </TableCell>
                          <TableCell className="py-1.5 text-xs text-muted-foreground">
                            {s.service_name ?? "-"}
                          </TableCell>
                          <TableCell className="py-1.5 text-xs text-muted-foreground text-right">
                            {s.first_event_time
                              ? new Date(s.first_event_time).toLocaleTimeString()
                              : "-"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </section>
          </div>

          {/* Right column: 1/3 */}
          <div className="space-y-6">
            <section className="animate-in stagger-3">
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                Top Downloads
              </h3>
              {!topAgents || topAgents.length === 0 ? (
                <EmptyState
                  icon={Download}
                  title="No download data"
                  description="Download stats will appear once agents are installed."
                />
              ) : (
                <div className="rounded-md border border-border p-3">
                  <TopDownloadsBar items={topAgents.slice(0, 8).map((a: any) => ({ name: a.name, value: a.download_count ?? a.value ?? 0 }))} />
                </div>
              )}
            </section>
          </div>
        </div>
      </div>
    </>
  );
}
