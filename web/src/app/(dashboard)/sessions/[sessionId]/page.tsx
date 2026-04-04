"use client";

import { use } from "react";
import { formatDistanceToNow, format } from "date-fns";
import { useOtelSession } from "@/hooks/use-api";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface OtelEvent {
  timestamp: string;
  event_name: string;
  body?: string;
  prompt?: string;
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  duration_ms?: number;
  tool_name?: string;
  tool_success?: boolean;
  decision?: string;
  [key: string]: unknown;
}

interface OtelSessionData {
  session_id: string;
  events: OtelEvent[];
  traces: unknown[];
  service_name: string;
}

function formatDuration(ms: number) {
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function EventBubble({ event }: { event: OtelEvent }) {
  const time = formatDistanceToNow(new Date(event.timestamp), { addSuffix: true });

  switch (event.event_name) {
    case "user_prompt":
      return (
        <div className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className="h-3 w-3 rounded-full bg-blue-500 ring-4 ring-blue-500/20" />
            <div className="w-px flex-1 bg-border" />
          </div>
          <div className="mb-4 flex-1 pb-2">
            <div className="max-w-[80%] rounded-lg rounded-tl-none border bg-blue-50 px-4 py-3 dark:bg-blue-950/30">
              <p className="text-sm whitespace-pre-wrap">{event.prompt ?? event.body ?? "—"}</p>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{time}</p>
          </div>
        </div>
      );

    case "api_request":
      return (
        <div className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className="h-3 w-3 rounded-full bg-violet-500 ring-4 ring-violet-500/20" />
            <div className="w-px flex-1 bg-border" />
          </div>
          <div className="mb-4 ml-auto max-w-[80%] pb-2">
            <div className="rounded-lg rounded-tr-none border bg-violet-50 px-4 py-3 dark:bg-violet-950/30">
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                {event.model && <Badge variant="outline" className="text-xs">{event.model}</Badge>}
                {event.input_tokens != null && <span>{event.input_tokens.toLocaleString()} in</span>}
                {event.output_tokens != null && <span>{event.output_tokens.toLocaleString()} out</span>}
                {event.duration_ms != null && <span>{formatDuration(event.duration_ms)}</span>}
              </div>
              {event.body && <p className="mt-1 text-sm whitespace-pre-wrap">{event.body}</p>}
            </div>
            <p className="mt-1 text-right text-xs text-muted-foreground">{time}</p>
          </div>
        </div>
      );

    case "tool_result":
      return (
        <div className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className="h-3 w-3 rounded-full bg-amber-500 ring-4 ring-amber-500/20" />
            <div className="w-px flex-1 bg-border" />
          </div>
          <div className="mb-4 ml-8 flex-1 pb-2">
            <div className="rounded-lg border bg-amber-50 px-4 py-3 dark:bg-amber-950/30">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-medium">{event.tool_name ?? "tool"}</span>
                <Badge variant={event.tool_success === false ? "destructive" : "secondary"} className="text-xs">
                  {event.tool_success === false ? "failed" : "success"}
                </Badge>
                {event.duration_ms != null && <span className="text-xs text-muted-foreground">{formatDuration(event.duration_ms)}</span>}
              </div>
              {event.body && <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap line-clamp-4">{event.body}</p>}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{time}</p>
          </div>
        </div>
      );

    case "tool_decision":
      return (
        <div className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className="h-2.5 w-2.5 rounded-full bg-gray-400 ring-4 ring-gray-400/20" />
            <div className="w-px flex-1 bg-border" />
          </div>
          <div className="mb-3 flex items-center gap-2 pb-1">
            <Badge variant={event.decision === "denied" ? "destructive" : "secondary"} className="text-xs">
              {event.decision ?? "approved"}
            </Badge>
            {event.tool_name && <span className="font-mono text-xs text-muted-foreground">{event.tool_name}</span>}
            <span className="text-xs text-muted-foreground">{time}</span>
          </div>
        </div>
      );

    default:
      return (
        <div className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className="h-2 w-2 rounded-full bg-gray-300" />
            <div className="w-px flex-1 bg-border" />
          </div>
          <div className="mb-3 pb-1">
            <p className="text-xs text-muted-foreground">
              <span className="font-mono">{event.event_name}</span>
              {event.body ? ` — ${event.body}` : ""}
              <span className="ml-2">{time}</span>
            </p>
          </div>
        </div>
      );
  }
}

export default function SessionDetailPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const { data, isLoading } = useOtelSession(sessionId);
  const session = data as OtelSessionData | undefined;

  const events = session?.events ?? [];
  const totalTokensIn = events.reduce((sum, e) => sum + (e.input_tokens ?? 0), 0);
  const totalTokensOut = events.reduce((sum, e) => sum + (e.output_tokens ?? 0), 0);
  const totalDuration = events.length >= 2
    ? new Date(events[events.length - 1].timestamp).getTime() - new Date(events[0].timestamp).getTime()
    : 0;
  const model = events.find((e) => e.model)?.model;

  return (
    <DashboardShell>
      <PageHeader
        title={`Session ${sessionId.slice(0, 12)}…`}
        breadcrumbs={[{ label: "Dashboard", href: "/" }, { label: "Sessions", href: "/sessions" }, { label: sessionId.slice(0, 12) }]}
      />
      <DashboardContent>
        {isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-24 w-full" />
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16 w-full" />)}
          </div>
        ) : (
          <div className="space-y-6">
            {/* Metadata card */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Session Info</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-5">
                  <div>
                    <p className="text-xs text-muted-foreground">Session ID</p>
                    <p className="font-mono text-xs">{sessionId}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Service</p>
                    <p className="text-xs">{session?.service_name ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Tokens</p>
                    <p className="text-xs">{totalTokensIn.toLocaleString()} in / {totalTokensOut.toLocaleString()} out</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Duration</p>
                    <p className="text-xs">{totalDuration ? formatDuration(totalDuration) : "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Model</p>
                    <p className="text-xs">{model ?? "—"}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Conversation timeline */}
            {!events.length ? (
              <p className="text-sm text-muted-foreground">No events in this session.</p>
            ) : (
              <div className="pl-1">
                {events.map((event, i) => (
                  <EventBubble key={`${event.timestamp}-${i}`} event={event} />
                ))}
                {/* Terminal dot */}
                <div className="flex gap-3">
                  <div className="flex flex-col items-center">
                    <div className="h-2 w-2 rounded-full bg-border" />
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </DashboardContent>
    </DashboardShell>
  );
}
