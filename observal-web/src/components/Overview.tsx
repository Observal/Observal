import { useQuery } from "urql";
import { OVERVIEW_QUERY } from "@/lib/queries";
import { StatCard, PageHeader, Spinner, Card } from "@/components/ui";
import { Activity, Layers, Zap, AlertTriangle } from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 19).replace("T", " ");
}

export function Overview() {
  const [result] = useQuery({ query: OVERVIEW_QUERY, variables: { start: daysAgo(30), end: daysAgo(0) } });
  const { data, fetching, error } = result;

  if (fetching) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;
  if (error) return <p className="text-destructive">Error: {error.message}</p>;

  const stats = data?.overview;
  const trends = data?.trends ?? [];

  return (
    <div>
      <PageHeader title="Overview" description="Enterprise telemetry at a glance" />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Total Traces" value={stats?.totalTraces ?? 0} icon={<Activity className="h-4 w-4" />} />
        <StatCard title="Total Spans" value={stats?.totalSpans ?? 0} icon={<Layers className="h-4 w-4" />} />
        <StatCard title="Tool Calls Today" value={stats?.toolCallsToday ?? 0} subtitle="Last 24h" icon={<Zap className="h-4 w-4" />} />
        <StatCard title="Errors Today" value={stats?.errorsToday ?? 0}
          subtitle={stats?.errorsToday > 0 ? "Needs attention" : "All clear"}
          trend={stats?.errorsToday > 0 ? "down" : "neutral"}
          icon={<AlertTriangle className="h-4 w-4" />} />
      </div>

      {trends.length > 0 && (
        <Card className="mt-6">
          <h3 className="mb-4 text-sm font-medium text-muted-foreground">Traces & Errors (30 days)</h3>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={trends}>
              <defs>
                <linearGradient id="gTraces" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gErrors" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" tick={{ fontSize: 12, fill: "#a1a1aa" }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 12, fill: "#a1a1aa" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, fontSize: 13 }} />
              <Area type="monotone" dataKey="traces" stroke="#3b82f6" fill="url(#gTraces)" strokeWidth={2} />
              <Area type="monotone" dataKey="errors" stroke="#ef4444" fill="url(#gErrors)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
      )}
    </div>
  );
}
