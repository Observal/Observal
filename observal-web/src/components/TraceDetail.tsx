import { useParams, Link } from "react-router-dom";
import { useQuery, useSubscription } from "urql";
import { TRACE_DETAIL_QUERY, SPAN_SUBSCRIPTION } from "@/lib/queries";
import { PageHeader, Card, Badge, DataTable, Spinner } from "@/components/ui";
import { ArrowLeft, CheckCircle2, XCircle, Minus } from "lucide-react";

export function TraceDetail() {
  const { traceId } = useParams<{ traceId: string }>();
  const [result] = useQuery({ query: TRACE_DETAIL_QUERY, variables: { traceId } });
  const [subResult] = useSubscription({ query: SPAN_SUBSCRIPTION, variables: { traceId } });
  const { data, fetching, error } = result;

  if (fetching) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;
  if (error) return <p className="text-destructive">Error: {error.message}</p>;

  const trace = data?.trace;
  if (!trace) return <p className="text-muted-foreground">Trace not found.</p>;

  const spanColumns = [
    { key: "type", label: "Type", render: (s: any) => <Badge variant="outline">{s.type}</Badge> },
    { key: "name", label: "Name", className: "font-medium" },
    { key: "method", label: "Method", className: "font-mono text-xs text-muted-foreground",
      render: (s: any) => s.method || "—" },
    { key: "status", label: "Status",
      render: (s: any) => s.status === "error"
        ? <Badge variant="destructive">error</Badge>
        : s.status === "success"
        ? <Badge variant="success">success</Badge>
        : <Badge variant="outline">{s.status}</Badge> },
    { key: "latencyMs", label: "Latency", className: "text-right",
      render: (s: any) => s.latencyMs ? `${s.latencyMs}ms` : "—" },
    { key: "schema", label: "Schema", className: "text-center",
      render: (s: any) => s.toolSchemaValid === true
        ? <CheckCircle2 className="inline h-4 w-4 text-success" />
        : s.toolSchemaValid === false
        ? <XCircle className="inline h-4 w-4 text-destructive" />
        : <Minus className="inline h-4 w-4 text-muted-foreground" /> },
  ];

  return (
    <div>
      <Link to="/traces" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Back to traces
      </Link>

      <PageHeader title={`Trace ${trace.traceId.slice(0, 12)}…`} description={trace.name || undefined} />

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card className="p-4">
          <p className="text-xs text-muted-foreground">Type</p>
          <p className="mt-1 font-medium">{trace.traceType}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-muted-foreground">Spans</p>
          <p className="mt-1 font-medium">{trace.spans.length}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-muted-foreground">Start</p>
          <p className="mt-1 text-sm">{new Date(trace.startTime).toLocaleString()}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-muted-foreground">End</p>
          <p className="mt-1 text-sm">{trace.endTime ? new Date(trace.endTime).toLocaleString() : "ongoing"}</p>
        </Card>
      </div>

      <h3 className="mb-3 text-sm font-medium text-muted-foreground">Spans ({trace.spans.length})</h3>
      <DataTable columns={spanColumns} data={trace.spans} />

      {trace.scores.length > 0 && (
        <div className="mt-6">
          <h3 className="mb-3 text-sm font-medium text-muted-foreground">Scores</h3>
          <DataTable columns={[
            { key: "name", label: "Name", className: "font-medium" },
            { key: "source", label: "Source", render: (s: any) => <Badge variant="outline">{s.source}</Badge> },
            { key: "value", label: "Value", className: "text-right font-mono" },
          ]} data={trace.scores} />
        </div>
      )}

      {subResult.data && (
        <div className="mt-4 rounded-md border border-primary/20 bg-primary/5 p-3 text-sm">
          <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-primary" />
          Live: {subResult.data.spanCreated.name} ({subResult.data.spanCreated.status})
        </div>
      )}
    </div>
  );
}
