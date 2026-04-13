"use client";

import { useState } from "react";
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from "@/components/ui/resizable";
import JsonView from "react18-json-view";
import "react18-json-view/src/style.css";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { SpanTree, type Span } from "./span-tree";

function isLifecycleSpan(span: Span): boolean {
  return span.input == null && span.output == null;
}

interface Trace {
  trace_id: string;
  parent_trace_id?: string;
  trace_type: string;
  mcp_id?: string;
  agent_id?: string;
  user_id?: string;
  session_id?: string;
  ide?: string;
  name?: string;
  start_time: string;
  end_time?: string;
  input?: unknown;
  output?: unknown;
  tags?: string[];
  metadata?: Record<string, unknown>;
  spans?: Span[];
  scores?: { score_id: string; name: string; value?: number; string_value?: string; source: string }[];
}

export function TraceDetail({ trace, isLoading }: { trace?: Trace; isLoading: boolean }) {
  const [selectedSpan, setSelectedSpan] = useState<Span | null>(null);

  if (isLoading) {
    return <div className="space-y-4"><Skeleton className="h-24 w-full" /><Skeleton className="h-[500px] w-full" /></div>;
  }
  if (!trace) {
    return <p className="text-muted-foreground">Trace not found.</p>;
  }

  const userPrompt = typeof trace.input === "string" ? trace.input : null;

  return (
    <div className="space-y-4">
      {/* User prompt bubble */}
      {userPrompt && (
        <div className="flex gap-3 items-start">
          <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-semibold">U</div>
          <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-3 text-sm max-w-[85%] whitespace-pre-wrap">{userPrompt}</div>
        </div>
      )}

      {/* Trace metadata */}
      <Card>
        <CardContent className="pt-4">
          <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm md:grid-cols-4">
            <div><span className="text-muted-foreground">Trace ID</span><p className="font-mono text-xs">{trace.trace_id}</p></div>
            <div><span className="text-muted-foreground">Type</span><p><Badge variant="outline">{trace.trace_type}</Badge></p></div>
            {trace.session_id && <div><span className="text-muted-foreground">Session</span><p className="font-mono text-xs truncate">{trace.session_id}</p></div>}
            {trace.user_id && <div><span className="text-muted-foreground">User</span><p className="truncate">{trace.user_id}</p></div>}
            {trace.ide && <div><span className="text-muted-foreground">IDE</span><p>{trace.ide}</p></div>}
            <div><span className="text-muted-foreground">Start</span><p>{new Date(trace.start_time).toLocaleString()}</p></div>
            {trace.end_time && <div><span className="text-muted-foreground">End</span><p>{new Date(trace.end_time).toLocaleString()}</p></div>}
            {trace.tags && trace.tags.length > 0 && (
              <div className="col-span-full"><span className="text-muted-foreground">Tags</span>
                <div className="flex gap-1 mt-1">{trace.tags.map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}</div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Split: span tree | span detail */}
      <ResizablePanelGroup orientation="horizontal" className="min-h-[500px] rounded-lg border">
        <ResizablePanel defaultSize={35} minSize={20}>
          <div className="h-full overflow-auto">
            <div className="px-3 py-2 text-xs font-medium text-muted-foreground border-b">Spans</div>
            <SpanTree spans={trace.spans ?? []} selectedId={selectedSpan?.span_id} onSelect={setSelectedSpan} />
          </div>
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel defaultSize={65} minSize={30}>
          <div className="h-full overflow-auto p-4">
            {selectedSpan ? (
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold">{selectedSpan.name}</h3>
                  <Badge variant="outline">{selectedSpan.type}</Badge>
                  <Badge variant={selectedSpan.status === "error" ? "destructive" : "secondary"}>{selectedSpan.status}</Badge>
                  {selectedSpan.latency_ms != null && <span className="text-sm text-muted-foreground">{selectedSpan.latency_ms}ms</span>}
                </div>
                {isLifecycleSpan(selectedSpan) && (
                  <Card className="border-dashed">
                    <CardContent className="pt-4">
                      <p className="text-sm text-muted-foreground mb-3">Lifecycle span — no conversation content. Metrics captured:</p>
                      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                        {selectedSpan.latency_ms != null && (
                          <div><span className="text-muted-foreground">Latency</span><p className="font-mono">{selectedSpan.latency_ms}ms</p></div>
                        )}
                        {(selectedSpan.token_input != null || selectedSpan.token_output != null) && (
                          <div><span className="text-muted-foreground">Tokens</span><p className="font-mono">{selectedSpan.token_input ?? 0} in / {selectedSpan.token_output ?? 0} out</p></div>
                        )}
                        <div><span className="text-muted-foreground">Type</span><p>{selectedSpan.type}</p></div>
                        <div><span className="text-muted-foreground">Status</span><p>{selectedSpan.status}</p></div>
                        <div><span className="text-muted-foreground">Start</span><p className="font-mono text-xs">{new Date(selectedSpan.start_time).toLocaleString()}</p></div>
                        {selectedSpan.end_time && (
                          <div><span className="text-muted-foreground">End</span><p className="font-mono text-xs">{new Date(selectedSpan.end_time).toLocaleString()}</p></div>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                )}
                {selectedSpan.input != null && (
                  <Card><CardHeader className="py-2 px-4"><CardTitle className="text-sm">Input</CardTitle></CardHeader>
                    <CardContent className="px-4 pb-3"><JsonView src={typeof selectedSpan.input === "string" ? JSON.parse(selectedSpan.input as string) : selectedSpan.input} collapsed={2} /></CardContent>
                  </Card>
                )}
                {selectedSpan.output != null && (
                  <Card><CardHeader className="py-2 px-4"><CardTitle className="text-sm">Output</CardTitle></CardHeader>
                    <CardContent className="px-4 pb-3"><JsonView src={typeof selectedSpan.output === "string" ? JSON.parse(selectedSpan.output as string) : selectedSpan.output} collapsed={2} /></CardContent>
                  </Card>
                )}
                {selectedSpan.error && (
                  <Card className="border-red-200"><CardHeader className="py-2 px-4"><CardTitle className="text-sm text-red-600">Error</CardTitle></CardHeader>
                    <CardContent className="px-4 pb-3 text-sm text-red-700 font-mono whitespace-pre-wrap">{selectedSpan.error}</CardContent>
                  </Card>
                )}
                {selectedSpan.metadata && Object.keys(selectedSpan.metadata).length > 0 && (
                  <Card><CardHeader className="py-2 px-4"><CardTitle className="text-sm">Metadata</CardTitle></CardHeader>
                    <CardContent className="px-4 pb-3"><JsonView src={selectedSpan.metadata} collapsed={2} /></CardContent>
                  </Card>
                )}
                {/* Scores for this span */}
                {trace.scores && trace.scores.filter((s) => s.score_id).length > 0 && (
                  <Card><CardHeader className="py-2 px-4"><CardTitle className="text-sm">Scores</CardTitle></CardHeader>
                    <CardContent className="px-4 pb-3">
                      <div className="space-y-1 text-sm">
                        {trace.scores.map((s) => (
                          <div key={s.score_id} className="flex justify-between">
                            <span>{s.name} <Badge variant="outline" className="text-[10px] ml-1">{s.source}</Badge></span>
                            <span className="font-mono">{s.value ?? s.string_value}</span>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Select a span to view details</p>
            )}
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
