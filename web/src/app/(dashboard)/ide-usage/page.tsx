"use client";

import { Monitor, Zap, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { DashboardCard } from "@/components/dashboard/dashboard-card";
import { StatCard } from "@/components/dashboard/stat-card";
import { NoData } from "@/components/dashboard/no-data";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { useIdeUsage } from "@/hooks/use-api";

const IDE_COLORS: Record<string, string> = {
  "Cursor": "hsl(var(--chart-1))",
  "Kiro IDE": "hsl(var(--chart-2))",
  "Kiro CLI": "hsl(var(--chart-3))",
  "Claude Code": "hsl(var(--chart-4))",
  "Gemini CLI": "hsl(var(--chart-5))",
  "VS Code": "hsl(210 80% 55%)",
  "Windsurf": "hsl(170 70% 45%)",
  "GitHub Copilot": "hsl(260 60% 55%)",
};

function getColor(ide: string) {
  return IDE_COLORS[ide] ?? "hsl(var(--muted-foreground))";
}

interface IdeRow {
  ide: string;
  traces: number;
  avg_latency_ms: number;
  error_count: number;
  error_rate: number;
}

export default function IdeUsagePage() {
  const { data, isLoading } = useIdeUsage();
  const ides = ((data as { ides?: IdeRow[] })?.ides ?? []) as IdeRow[];

  const byIde = ides.map((r) => ({
    name: r.ide,
    count: r.traces,
    avgLatency: Math.round(r.avg_latency_ms),
    errorRate: r.error_rate,
  }));

  const mostUsed = byIde.reduce((a, b) => (b.count > a.count ? b : a), byIde[0]);
  const fastest = byIde.filter((i) => i.count > 0).reduce((a, b) => (b.avgLatency < a.avgLatency ? b : a), byIde[0]);
  const reliable = byIde.filter((i) => i.count > 0).reduce((a, b) => (b.errorRate < a.errorRate ? b : a), byIde[0]);

  const stats = {
    mostUsed: mostUsed?.name ?? "—",
    fastest: fastest?.name ?? "—",
    reliable: reliable?.name ?? "—",
  };

  const hasData = byIde.length > 0;

  return (
    <DashboardShell>
      <PageHeader title="IDE Usage" />
      <DashboardContent>
        <div className="grid w-full grid-cols-1 gap-3 xl:grid-cols-3">
          <StatCard title="Most Used IDE" value={stats.mostUsed} icon={Monitor} />
          <StatCard title="Fastest IDE" value={stats.fastest} icon={Zap} description="Lowest avg latency" />
          <StatCard title="Most Reliable" value={stats.reliable} icon={ShieldCheck} description="Lowest error rate" />
        </div>

        <div className="mt-3 grid w-full grid-cols-1 gap-3 lg:grid-cols-2">
          <DashboardCard title="Trace Distribution by IDE" isLoading={isLoading}>
            {!hasData ? <NoData description="No trace data available yet." /> : (
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie data={byIde} dataKey="count" nameKey="name" cx="50%" cy="50%" innerRadius={60} outerRadius={100} paddingAngle={2}>
                    {byIde.map((e) => <Cell key={e.name} fill={getColor(e.name)} />)}
                  </Pie>
                  <Tooltip contentStyle={{ backgroundColor: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: "6px", fontSize: "12px" }} />
                  <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: "12px" }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </DashboardCard>

          <DashboardCard title="Traces per IDE Over Time" isLoading={isLoading}>
            <NoData description="Timeline data not available from this endpoint." />
          </DashboardCard>
        </div>

        <div className="mt-3">
          <DashboardCard title="IDE Breakdown" isLoading={isLoading}>
            {!hasData ? <NoData description="No IDE data." /> : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>IDE</TableHead>
                    <TableHead className="text-right">Traces</TableHead>
                    <TableHead className="text-right">Avg Latency</TableHead>
                    <TableHead className="text-right">Error Rate</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {byIde.sort((a, b) => b.count - a.count).map((row) => (
                    <TableRow key={row.name}>
                      <TableCell>
                        <span className="flex items-center gap-2">
                          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: getColor(row.name) }} />
                          {row.name}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">{row.count}</TableCell>
                      <TableCell className="text-right">{row.avgLatency}ms</TableCell>
                      <TableCell className="text-right">{(row.errorRate * 100).toFixed(1)}%</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </DashboardCard>
        </div>
      </DashboardContent>
    </DashboardShell>
  );
}
