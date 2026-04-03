import { useQuery } from "urql";
import { TRACES_QUERY } from "@/lib/queries";
import { PageHeader, DataTable, Badge, Spinner, EmptyState } from "@/components/ui";
import { Activity } from "lucide-react";
import { useNavigate } from "react-router-dom";

export function TraceExplorer() {
  const [result] = useQuery({ query: TRACES_QUERY, variables: { limit: 50 } });
  const navigate = useNavigate();
  const { data, fetching, error } = result;

  if (fetching) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;
  if (error) return <p className="text-destructive">Error: {error.message}</p>;

  const traces = data?.traces?.items ?? [];

  if (!traces.length) return <EmptyState icon={<Activity className="h-8 w-8" />} title="No traces yet" description="Submit an MCP server and start using it to generate traces." />;

  const columns = [
    { key: "traceId", label: "Trace ID", className: "font-mono text-xs",
      render: (r: any) => <span className="text-primary">{r.traceId.slice(0, 12)}…</span> },
    { key: "traceType", label: "Type",
      render: (r: any) => <Badge variant={r.traceType === "mcp" ? "default" : "outline"}>{r.traceType}</Badge> },
    { key: "name", label: "Name", render: (r: any) => r.name || <span className="text-muted-foreground">—</span> },
    { key: "spans", label: "Spans", className: "text-right", render: (r: any) => r.metrics.totalSpans },
    { key: "errors", label: "Errors", className: "text-right",
      render: (r: any) => r.metrics.errorCount > 0
        ? <Badge variant="destructive">{r.metrics.errorCount}</Badge>
        : <span className="text-muted-foreground">0</span> },
    { key: "latency", label: "Latency", className: "text-right",
      render: (r: any) => r.metrics.totalLatencyMs ? `${r.metrics.totalLatencyMs}ms` : <span className="text-muted-foreground">—</span> },
    { key: "startTime", label: "Time", className: "text-muted-foreground text-xs",
      render: (r: any) => new Date(r.startTime).toLocaleString() },
  ];

  return (
    <div>
      <PageHeader title="Traces" description={`${traces.length} recent traces`} />
      <DataTable columns={columns} data={traces} onRowClick={(r) => navigate(`/traces/${r.traceId}`)} />
    </div>
  );
}
