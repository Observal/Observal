import { useQuery } from "urql";
import { MCP_METRICS_QUERY } from "@/lib/queries";
import { useParams, Link } from "react-router-dom";
import { PageHeader, StatCard, Card, Spinner } from "@/components/ui";
import { ArrowLeft, Zap, AlertTriangle, Clock, Shield } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 19).replace("T", " ");
}

export function McpMetrics() {
  const { mcpId } = useParams<{ mcpId: string }>();
  const [result] = useQuery({ query: MCP_METRICS_QUERY, variables: { mcpId, start: daysAgo(30), end: daysAgo(0) } });
  const { data, fetching, error } = result;

  if (fetching) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;
  if (error) return <p className="text-destructive">Error: {error.message}</p>;

  const m = data?.mcpMetrics;
  if (!m) return <p className="text-muted-foreground">No metrics available.</p>;

  const latencyData = [
    { name: "p50", value: m.p50LatencyMs },
    { name: "p90", value: m.p90LatencyMs },
    { name: "p99", value: m.p99LatencyMs },
  ];

  return (
    <div>
      <Link to="/mcps" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Back to MCPs
      </Link>

      <PageHeader title="MCP Metrics" />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Tool Calls" value={m.toolCallCount} icon={<Zap className="h-4 w-4" />} />
        <StatCard title="Error Rate" value={`${(m.errorRate * 100).toFixed(1)}%`}
          trend={m.errorRate > 0.05 ? "down" : "neutral"} icon={<AlertTriangle className="h-4 w-4" />} />
        <StatCard title="Avg Latency" value={`${m.avgLatencyMs.toFixed(0)}ms`} icon={<Clock className="h-4 w-4" />} />
        <StatCard title="Schema Compliance" value={`${(m.schemaComplianceRate * 100).toFixed(0)}%`}
          trend={m.schemaComplianceRate > 0.95 ? "up" : "down"} icon={<Shield className="h-4 w-4" />} />
      </div>

      <Card className="mt-6">
        <h3 className="mb-4 text-sm font-medium text-muted-foreground">Latency Percentiles</h3>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={latencyData}>
            <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#a1a1aa" }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fontSize: 12, fill: "#a1a1aa" }} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, fontSize: 13 }} />
            <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
}
