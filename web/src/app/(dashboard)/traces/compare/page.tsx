"use client";

import { useState, useMemo } from "react";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { useTrace } from "@/hooks/use-api";
import { SpanTree, type Span } from "@/components/traces/span-tree";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { NoData } from "@/components/dashboard/no-data";
import { cn } from "@/lib/utils";

interface TraceData {
  id: string;
  traceId: string;
  startTime: string;
  endTime?: string;
  status: string;
  spans?: Span[];
  eval_scores?: Record<string, number>;
}

function traceMetrics(trace: TraceData | undefined) {
  if (!trace) return { latency: 0, toolCalls: 0, errors: 0 };
  const spans = trace.spans ?? [];
  const start = new Date(trace.startTime).getTime();
  const end = trace.endTime ? new Date(trace.endTime).getTime() : start;
  return {
    latency: end - start,
    toolCalls: spans.filter((s) => s.type === "tool_call").length,
    errors: spans.filter((s) => s.status === "error").length,
  };
}

function MetricCell({ label, a, b, lowerBetter = true }: { label: string; a: number; b: number; lowerBetter?: boolean }) {
  const better = lowerBetter ? a < b : a > b;
  const worse = lowerBetter ? a > b : a < b;
  return (
    <div className="flex items-center justify-between rounded px-2 py-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <div className="flex items-center gap-3 tabular-nums">
        <span className={cn(better && "text-green-600 font-medium", worse && "text-red-600 font-medium")}>{a}</span>
        <span className="text-muted-foreground">vs</span>
        <span className={cn(!better && !worse ? "" : better ? "text-red-600 font-medium" : "text-green-600 font-medium")}>{b}</span>
      </div>
    </div>
  );
}

function TracePanel({ trace, isLoading }: { trace: TraceData | undefined; isLoading: boolean }) {
  const [selectedSpan, setSelectedSpan] = useState<string>();
  if (isLoading) return <NoData isLoading />;
  if (!trace) return <NoData noDataText="Enter a trace ID above" />;
  const m = traceMetrics(trace);
  return (
    <div className="flex flex-col gap-3 overflow-y-auto p-3">
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded border p-2 text-center">
          <p className="text-xs text-muted-foreground">Latency</p>
          <p className="text-lg font-semibold tabular-nums">{m.latency}ms</p>
        </div>
        <div className="rounded border p-2 text-center">
          <p className="text-xs text-muted-foreground">Tool Calls</p>
          <p className="text-lg font-semibold tabular-nums">{m.toolCalls}</p>
        </div>
        <div className="rounded border p-2 text-center">
          <p className="text-xs text-muted-foreground">Errors</p>
          <p className="text-lg font-semibold tabular-nums">{m.errors}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <span className="text-muted-foreground">Status</span>
        <Badge variant="outline" className="w-fit text-[10px]">{trace.status}</Badge>
        <span className="text-muted-foreground">Spans</span>
        <span>{trace.spans?.length ?? 0}</span>
        <span className="text-muted-foreground">Start</span>
        <span>{new Date(trace.startTime).toLocaleString()}</span>
      </div>
      <div className="rounded-md border">
        <SpanTree spans={trace.spans ?? []} selectedId={selectedSpan} onSelect={(s) => setSelectedSpan(s.span_id)} />
      </div>
    </div>
  );
}

export default function TraceComparePage() {
  const [idA, setIdA] = useState("");
  const [idB, setIdB] = useState("");
  const [loadedA, setLoadedA] = useState<string>();
  const [loadedB, setLoadedB] = useState<string>();

  const traceA = useTrace(loadedA);
  const traceB = useTrace(loadedB);
  const a = traceA.data as TraceData | undefined;
  const b = traceB.data as TraceData | undefined;
  const mA = useMemo(() => traceMetrics(a), [a]);
  const mB = useMemo(() => traceMetrics(b), [b]);

  const scoresA = a?.eval_scores;
  const scoresB = b?.eval_scores;
  const dimensions = useMemo(() => {
    const keys = new Set([...Object.keys(scoresA ?? {}), ...Object.keys(scoresB ?? {})]);
    return Array.from(keys);
  }, [scoresA, scoresB]);

  return (
    <DashboardShell>
      <PageHeader
        title="Compare Traces"
        breadcrumbs={[
          { label: "Home", href: "/" },
          { label: "Traces", href: "/traces" },
          { label: "Compare" },
        ]}
      />
      <DashboardContent>
        <div className="flex flex-col gap-4">
          {/* Input row */}
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label className="mb-1 block text-xs text-muted-foreground">Trace A</label>
              <Input
                placeholder="Trace ID…"
                value={idA}
                onChange={(e) => setIdA(e.target.value)}
                className="h-8 text-sm font-mono"
              />
            </div>
            <div className="flex-1">
              <label className="mb-1 block text-xs text-muted-foreground">Trace B</label>
              <Input
                placeholder="Trace ID…"
                value={idB}
                onChange={(e) => setIdB(e.target.value)}
                className="h-8 text-sm font-mono"
              />
            </div>
            <Button
              size="sm"
              disabled={!idA.trim() || !idB.trim()}
              onClick={() => { setLoadedA(idA.trim()); setLoadedB(idB.trim()); }}
            >
              Compare
            </Button>
          </div>

          {/* Split panels */}
          <div className="min-h-[400px] rounded-md border">
            <ResizablePanelGroup orientation="horizontal">
              <ResizablePanel defaultSize={50} minSize={30}>
                <TracePanel trace={a} isLoading={traceA.isLoading} />
              </ResizablePanel>
              <ResizableHandle withHandle />
              <ResizablePanel defaultSize={50} minSize={30}>
                <TracePanel trace={b} isLoading={traceB.isLoading} />
              </ResizablePanel>
            </ResizablePanelGroup>
          </div>

          {/* Diff summary */}
          {a && b && (
            <div className="rounded-md border p-3">
              <h3 className="mb-2 text-sm font-medium">Metric Comparison</h3>
              <div className="space-y-1">
                <MetricCell label="Latency (ms)" a={mA.latency} b={mB.latency} lowerBetter />
                <MetricCell label="Tool Calls" a={mA.toolCalls} b={mB.toolCalls} lowerBetter />
                <MetricCell label="Errors" a={mA.errors} b={mB.errors} lowerBetter />
              </div>
            </div>
          )}

          {/* Eval score comparison */}
          {dimensions.length > 0 && (
            <div className="rounded-md border p-3">
              <h3 className="mb-2 text-sm font-medium">Eval Score Comparison</h3>
              <div className="space-y-1">
                {dimensions.map((dim) => (
                  <MetricCell
                    key={dim}
                    label={dim.replace(/_/g, " ")}
                    a={scoresA?.[dim] ?? 0}
                    b={scoresB?.[dim] ?? 0}
                    lowerBetter={false}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      </DashboardContent>
    </DashboardShell>
  );
}
