"use client";

import { Container, Skull, Timer, Terminal } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { DashboardCard } from "@/components/dashboard/dashboard-card";
import { StatCard } from "@/components/dashboard/stat-card";
import { NoData } from "@/components/dashboard/no-data";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { useSandboxMetrics } from "@/hooks/use-api";
import { format } from "date-fns";

interface SandboxData {
  total_runs: number;
  oom_count: number;
  oom_rate: number;
  timeout_count: number;
  timeout_rate: number;
  avg_exit_code: number;
  recent_runs: { span_id: string; name: string; exit_code: number; duration_ms: number; memory_mb: number; cpu_ms: number; oom: boolean; timestamp: string }[];
  cpu_over_time: { date: string; avg_cpu: number }[];
  memory_over_time: { date: string; avg_memory: number }[];
}

export default function SandboxMetricsPage() {
  const { data, isLoading } = useSandboxMetrics();
  const d = data as SandboxData | undefined;

  const stats = {
    total: d?.total_runs ?? 0,
    oomRate: d ? (d.oom_rate * 100).toFixed(1) : "0",
    timeoutRate: d ? (d.timeout_rate * 100).toFixed(1) : "0",
    avgExit: d?.avg_exit_code?.toFixed(1) ?? "0",
  };

  const cpuTimeline = (d?.cpu_over_time ?? []).map((r) => ({ date: r.date, cpu: Math.round(r.avg_cpu) }));
  const memTimeline = (d?.memory_over_time ?? []).map((r) => ({ date: r.date, memory: Math.round(r.avg_memory) }));
  const rows = d?.recent_runs ?? [];
  const hasData = stats.total > 0;

  return (
    <DashboardShell>
      <PageHeader title="Sandbox Metrics" />
      <DashboardContent>
        <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard title="Total Runs" value={stats.total} icon={Terminal} />
          <StatCard title="OOM Rate" value={`${stats.oomRate}%`} icon={Skull} />
          <StatCard title="Timeout Rate" value={`${stats.timeoutRate}%`} icon={Timer} />
          <StatCard title="Avg Exit Code" value={stats.avgExit} icon={Container} />
        </div>

        <div className="mt-3 grid w-full grid-cols-1 gap-3 lg:grid-cols-2">
          <DashboardCard title="CPU Usage Over Time" isLoading={isLoading}>
            {!hasData ? <NoData description="No sandbox data."><Container className="mx-auto mt-2 h-8 w-8 text-muted-foreground/40" /></NoData> : (
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={cpuTimeline} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--muted-gray))" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} tickLine={false} axisLine={false} unit="%" />
                  <Tooltip contentStyle={{ backgroundColor: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: "6px", fontSize: "12px" }} />
                  <Area type="monotone" dataKey="cpu" stroke="hsl(var(--chart-1))" fill="hsl(var(--chart-1))" fillOpacity={0.15} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </DashboardCard>

          <DashboardCard title="Memory Usage Over Time" isLoading={isLoading}>
            {!hasData ? <NoData description="No sandbox data."><Container className="mx-auto mt-2 h-8 w-8 text-muted-foreground/40" /></NoData> : (
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={memTimeline} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--muted-gray))" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} tickLine={false} axisLine={false} unit="MB" />
                  <Tooltip contentStyle={{ backgroundColor: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: "6px", fontSize: "12px" }} />
                  <Area type="monotone" dataKey="memory" stroke="hsl(var(--chart-2))" fill="hsl(var(--chart-2))" fillOpacity={0.15} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </DashboardCard>
        </div>

        <div className="mt-3">
          <DashboardCard title="Recent Sandbox Runs" isLoading={isLoading}>
            {!hasData ? (
              <NoData description="No sandbox executions recorded yet.">
                <Container className="mx-auto mt-2 h-8 w-8 text-muted-foreground/40" />
              </NoData>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Sandbox</TableHead>
                    <TableHead>Exit Code</TableHead>
                    <TableHead className="text-right">Duration</TableHead>
                    <TableHead className="text-right">Memory</TableHead>
                    <TableHead className="text-right">CPU</TableHead>
                    <TableHead>OOM</TableHead>
                    <TableHead>Timestamp</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.slice(0, 50).map((s) => {
                    const exitCode = s.exit_code ?? 0;
                    return (
                      <TableRow key={s.span_id}>
                        <TableCell className="font-medium">{s.name}</TableCell>
                        <TableCell>
                          <Badge variant={exitCode === 0 ? "default" : "destructive"} className={exitCode === 0 ? "bg-light-green text-dark-green" : ""}>
                            {exitCode}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">{s.duration_ms ?? "—"}ms</TableCell>
                        <TableCell className="text-right">{s.memory_mb ?? "—"}MB</TableCell>
                        <TableCell className="text-right">{s.cpu_ms ?? "—"}ms</TableCell>
                        <TableCell>
                          {s.oom ? <Badge variant="destructive">OOM</Badge> : <span className="text-xs text-muted-foreground">No</span>}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {s.timestamp ? format(new Date(s.timestamp), "MMM d, HH:mm:ss") : "—"}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </DashboardCard>
        </div>
      </DashboardContent>
    </DashboardShell>
  );
}
