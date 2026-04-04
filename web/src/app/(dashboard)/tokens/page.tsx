"use client";

import { useState } from "react";
import { Coins } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { StatCard } from "@/components/dashboard/stat-card";
import { DashboardCard } from "@/components/dashboard/dashboard-card";
import { TrendChart } from "@/components/dashboard/trend-chart";
import { TimeRangeSelect } from "@/components/dashboard/time-range-select";
import { NoData } from "@/components/dashboard/no-data";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useTokenStats } from "@/hooks/use-api";

interface TokenStats {
  total_input: number;
  total_output: number;
  total_tokens: number;
  avg_per_trace: number;
  by_agent: { agent_id: string; name: string; input: number; output: number; total: number; traces: number }[];
  by_mcp: { mcp_id: string; name: string; input: number; output: number; total: number; traces: number }[];
  over_time: { date: string; input: number; output: number }[];
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function UsageTable({ data, isLoading }: { data: { name: string; input: number; output: number; total: number; traces: number }[] | undefined; isLoading: boolean }) {
  if (isLoading) return <NoData isLoading />;
  if (!data?.length) return <NoData noDataText="No data" />;
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="h-9 px-3 text-xs">Name</TableHead>
            <TableHead className="h-9 px-3 text-xs text-right">Input</TableHead>
            <TableHead className="h-9 px-3 text-xs text-right">Output</TableHead>
            <TableHead className="h-9 px-3 text-xs text-right">Total</TableHead>
            <TableHead className="h-9 px-3 text-xs text-right">Traces</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((row) => (
            <TableRow key={row.name}>
              <TableCell className="px-3 py-2 text-sm">{row.name}</TableCell>
              <TableCell className="px-3 py-2 text-right text-sm tabular-nums">{fmt(row.input)}</TableCell>
              <TableCell className="px-3 py-2 text-right text-sm tabular-nums">{fmt(row.output)}</TableCell>
              <TableCell className="px-3 py-2 text-right text-sm font-medium tabular-nums">{fmt(row.total)}</TableCell>
              <TableCell className="px-3 py-2 text-right text-sm tabular-nums">{row.traces}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default function TokensPage() {
  const [range, setRange] = useState("7d");
  const { data, isLoading } = useTokenStats();
  const d = data as TokenStats | undefined;

  const avgPerTrace = d?.avg_per_trace ?? 0;

  return (
    <DashboardShell>
      <PageHeader
        title="Token Usage"
        breadcrumbs={[{ label: "Home", href: "/" }, { label: "Token Usage" }]}
        actionButtonsLeft={<TimeRangeSelect value={range} onChange={setRange} />}
      />
      <DashboardContent>
        <div className="flex flex-col gap-4">
          {/* Stat cards */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard title="Total Input Tokens" value={isLoading ? "—" : fmt(d?.total_input ?? 0)} icon={Coins} />
            <StatCard title="Total Output Tokens" value={isLoading ? "—" : fmt(d?.total_output ?? 0)} icon={Coins} />
            <StatCard title="Total Tokens" value={isLoading ? "—" : fmt(d?.total_tokens ?? 0)} icon={Coins} />
            <StatCard title="Avg Tokens / Trace" value={isLoading ? "—" : fmt(avgPerTrace)} icon={Coins} />
          </div>

          {/* Chart */}
          <DashboardCard title="Tokens Over Time" isLoading={isLoading}>
            {!d?.over_time?.length ? (
              <NoData description="Token usage data will appear as traces are collected." />
            ) : (
              <div className="h-72">
                <TrendChart
                  data={d.over_time}
                  lines={[
                    { key: "input", color: "hsl(var(--chart-1))", label: "Input Tokens" },
                    { key: "output", color: "hsl(var(--chart-2))", label: "Output Tokens" },
                  ]}
                  height={288}
                />
              </div>
            )}
          </DashboardCard>

          {/* By agent */}
          <DashboardCard title="Token Usage by Agent" isLoading={isLoading}>
            <UsageTable data={d?.by_agent} isLoading={isLoading} />
          </DashboardCard>

          {/* By MCP */}
          <DashboardCard title="Token Usage by MCP Server" isLoading={isLoading}>
            <UsageTable data={d?.by_mcp} isLoading={isLoading} />
          </DashboardCard>
        </div>
      </DashboardContent>
    </DashboardShell>
  );
}
