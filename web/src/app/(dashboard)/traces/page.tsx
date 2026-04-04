"use client";

import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { useOtelTraces } from "@/hooks/use-api";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { TraceList } from "@/components/traces/trace-list";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/components/registry/status-badge";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface OtelTrace {
  TraceId: string;
  SpanId: string;
  ParentSpanId?: string;
  SpanName: string;
  Duration: number;
  StatusCode: string;
  SpanAttributes?: Record<string, unknown>;
  session_id?: string;
  service_name?: string;
  Timestamp?: string;
}

function formatNanos(ns: number) {
  const ms = ns / 1_000_000;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function OtelTraceTable() {
  const router = useRouter();
  const { data, isLoading } = useOtelTraces();
  const traces = (data ?? []) as OtelTrace[];

  if (isLoading) {
    return <div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>;
  }

  if (!traces.length) {
    return (
      <div className="flex flex-col items-center justify-center rounded-md border border-dashed py-16">
        <p className="text-sm font-medium">No OTel traces yet</p>
        <p className="mt-1 max-w-md text-center text-xs text-muted-foreground">
          OTel traces appear when IDEs with native OpenTelemetry support send data to Observal.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="h-9 px-3 text-xs">Trace ID</TableHead>
            <TableHead className="h-9 px-3 text-xs">Span Name</TableHead>
            <TableHead className="h-9 px-3 text-xs">Service</TableHead>
            <TableHead className="h-9 px-3 text-xs">Duration</TableHead>
            <TableHead className="h-9 px-3 text-xs">Status</TableHead>
            <TableHead className="h-9 px-3 text-xs">Session</TableHead>
            <TableHead className="h-9 px-3 text-xs">Timestamp</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {traces.map((t, i) => (
            <TableRow
              key={`${t.TraceId}-${t.SpanId}-${i}`}
              className="cursor-pointer"
              onClick={() => t.session_id ? router.push(`/sessions/${t.session_id}`) : undefined}
            >
              <TableCell className="px-3 py-2 font-mono text-xs">{t.TraceId?.slice(0, 12)}…</TableCell>
              <TableCell className="px-3 py-2 text-sm">{t.SpanName}</TableCell>
              <TableCell className="px-3 py-2 text-xs text-muted-foreground">{t.service_name ?? "—"}</TableCell>
              <TableCell className="px-3 py-2 text-xs">{formatNanos(t.Duration)}</TableCell>
              <TableCell className="px-3 py-2"><StatusBadge status={t.StatusCode?.toLowerCase() ?? "success"} /></TableCell>
              <TableCell className="px-3 py-2 font-mono text-xs text-muted-foreground">{t.session_id?.slice(0, 8) ?? "—"}</TableCell>
              <TableCell className="px-3 py-2 text-xs text-muted-foreground">
                {t.Timestamp ? formatDistanceToNow(new Date(t.Timestamp), { addSuffix: true }) : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default function TracesPage() {
  return (
    <DashboardShell>
      <PageHeader
        title="Traces"
        breadcrumbs={[{ label: "Home", href: "/" }, { label: "Traces" }]}
      />
      <DashboardContent>
        <Tabs defaultValue="shim">
          <TabsList>
            <TabsTrigger value="shim">Shim Traces</TabsTrigger>
            <TabsTrigger value="otel">OTel Traces</TabsTrigger>
          </TabsList>
          <TabsContent value="shim" className="mt-3">
            <TraceList />
          </TabsContent>
          <TabsContent value="otel" className="mt-3">
            <OtelTraceTable />
          </TabsContent>
        </Tabs>
      </DashboardContent>
    </DashboardShell>
  );
}
