"use client";

import { useState } from "react";
import {
  Server,
  Bot,
  Users,
  Wrench,
  MessageSquare,
  ListTree,
  Clock,
  BarChart3,
  ArrowRight,
  Activity,
  Zap,
} from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { StatCard } from "@/components/dashboard/stat-card";
import { TopItemsCard } from "@/components/dashboard/top-items-card";
import { TrendChart } from "@/components/dashboard/trend-chart";
import { DashboardCard } from "@/components/dashboard/dashboard-card";
import { TimeRangeSelect } from "@/components/dashboard/time-range-select";
import { NoData } from "@/components/dashboard/no-data";
import { LatencyHeatmap } from "@/components/dashboard/latency-heatmap";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import {
  useOverviewStats,
  useTopMcps,
  useTopAgents,
  useTrends,
  useLatencyHeatmap,
  useOtelStats,
} from "@/hooks/use-api";

export default function DashboardPage() {
  const [range, setRange] = useState("7d");
  const stats = useOverviewStats();
  const topMcps = useTopMcps();
  const topAgents = useTopAgents();
  const trends = useTrends();
  const heatmap = useLatencyHeatmap();
  const otelStats = useOtelStats();

  const s = stats.data as
    | {
        total_mcps: number;
        total_agents: number;
        total_users: number;
        total_tool_calls_today: number;
        total_agent_interactions_today: number;
      }
    | undefined;

  const isLoading = stats.isLoading;
  const hasData = !!s;

  const os = otelStats.data as
    | { total_sessions: number; total_prompts: number; total_api_requests: number }
    | undefined;

  return (
    <DashboardShell>
      <PageHeader
        title="Home"
        actionButtonsLeft={
          <TimeRangeSelect value={range} onChange={setRange} />
        }
      />
      <DashboardContent>
        <div className="grid w-full grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-6">
          {/* Stat cards row - show real data or zeros */}
          <StatCard
            title="MCP Servers"
            value={isLoading ? "—" : (s?.total_mcps ?? 0)}
            icon={Server}
          />
          <StatCard
            title="Agents"
            value={isLoading ? "—" : (s?.total_agents ?? 0)}
            icon={Bot}
          />
          <StatCard
            title="Users"
            value={isLoading ? "—" : (s?.total_users ?? 0)}
            icon={Users}
          />
          <StatCard
            title="Tool Calls Today"
            value={isLoading ? "—" : (s?.total_tool_calls_today ?? 0)}
            icon={Wrench}
          />
          <StatCard
            title="Interactions Today"
            value={isLoading ? "—" : (s?.total_agent_interactions_today ?? 0)}
            icon={MessageSquare}
          />
          {/* Extra stat for visual balance */}
          <StatCard
            title="Active Traces"
            value={isLoading ? "—" : 0}
            icon={Activity}
          />
          <StatCard
            title="OTel Sessions"
            value={otelStats.isLoading ? "—" : (os?.total_sessions ?? 0)}
            icon={Zap}
          />
          <StatCard
            title="OTel Prompts"
            value={otelStats.isLoading ? "—" : (os?.total_prompts ?? 0)}
            icon={MessageSquare}
          />
          <StatCard
            title="OTel API Requests"
            value={otelStats.isLoading ? "—" : (os?.total_api_requests ?? 0)}
            icon={Activity}
          />

          {/* Top items row */}
          <TopItemsCard
            title="Top MCP Servers"
            data={topMcps.data as { id: string; name: string; value: number }[] | undefined}
            isLoading={topMcps.isLoading}
            linkPrefix="/mcps/"
            className="col-span-1 xl:col-span-3"
          />
          <TopItemsCard
            title="Top Agents"
            data={topAgents.data as { id: string; name: string; value: number }[] | undefined}
            isLoading={topAgents.isLoading}
            linkPrefix="/agents/"
            className="col-span-1 xl:col-span-3"
          />

          {/* Trends chart */}
          <DashboardCard
            title="Activity Over Time"
            isLoading={trends.isLoading}
            className="col-span-1 lg:col-span-full"
          >
            {!trends.data || !(trends.data as unknown[]).length ? (
              <NoData description="Trends will appear as submissions and user activity are recorded." />
            ) : (
              <div className="h-72">
                <TrendChart
                  data={trends.data as Array<{ date: string; submissions: number; users: number }>}
                  lines={[
                    { key: "submissions", color: "hsl(var(--chart-1))", label: "Submissions" },
                    { key: "users", color: "hsl(var(--chart-2))", label: "Users" },
                  ]}
                  height={288}
                />
              </div>
            )}
          </DashboardCard>

          {/* Latency Heatmap */}
          <DashboardCard
            title="Latency Heatmap"
            isLoading={heatmap.isLoading}
            className="col-span-1 lg:col-span-full"
          >
            {heatmap.isLoading ? null : !heatmap.data?.length ? (
              <NoData description="Latency heatmap data will appear as tool call telemetry is collected." />
            ) : (
              <LatencyHeatmap data={heatmap.data as { name: string; hour: number; p50: number; p90: number; p99: number }[]} />
            )}
          </DashboardCard>

          {/* Quick navigation cards - fills the page when there's no data */}
          <QuickNavCard
            title="Traces"
            description="View all traces from your agentic coding sessions"
            href="/traces"
            icon={ListTree}
            className="col-span-1 xl:col-span-2"
          />
          <QuickNavCard
            title="Sessions"
            description="Browse sessions grouped by session ID"
            href="/sessions"
            icon={Clock}
            className="col-span-1 xl:col-span-2"
          />
          <QuickNavCard
            title="Scores"
            description="Evaluation scores from LLM-as-judge and human feedback"
            href="/scores"
            icon={BarChart3}
            className="col-span-1 xl:col-span-2"
          />
        </div>
      </DashboardContent>
    </DashboardShell>
  );
}

function QuickNavCard({
  title,
  description,
  href,
  icon: Icon,
  className,
}: {
  title: string;
  description: string;
  href: string;
  icon: typeof Server;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={`group flex items-start gap-3 rounded-lg border bg-card p-4 shadow-xs transition-colors hover:bg-accent ${className ?? ""}`}
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1">
          <span className="text-sm font-medium">{title}</span>
          <ArrowRight className="h-3 w-3 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed">{description}</p>
      </div>
    </Link>
  );
}
