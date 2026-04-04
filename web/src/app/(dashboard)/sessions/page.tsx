"use client";

import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { useOtelSessions } from "@/hooks/use-api";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

interface OtelSession {
  session_id: string;
  first_event_time: string;
  last_event_time: string;
  prompt_count: number;
  api_request_count: number;
  tool_result_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  model: string;
  service_name: string;
}

function formatDuration(start: string, end: string) {
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

export default function SessionsPage() {
  const router = useRouter();
  const { data, isLoading } = useOtelSessions();
  const sessions = (data ?? []) as OtelSession[];

  return (
    <DashboardShell>
      <PageHeader title="Sessions" breadcrumbs={[{ label: "Dashboard", href: "/" }, { label: "Sessions" }]} />
      <DashboardContent>
        {isLoading ? (
          <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
        ) : !sessions.length ? (
          <div className="flex flex-col items-center justify-center rounded-md border border-dashed py-16">
            <p className="text-sm font-medium">No sessions yet</p>
            <p className="mt-1 max-w-md text-center text-xs text-muted-foreground">
              Sessions are created automatically when you use Claude Code, Codex, or Gemini CLI with Observal telemetry enabled.
            </p>
          </div>
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="h-9 px-3 text-xs">Session ID</TableHead>
                  <TableHead className="h-9 px-3 text-xs">Service</TableHead>
                  <TableHead className="h-9 px-3 text-xs">Prompts</TableHead>
                  <TableHead className="h-9 px-3 text-xs">API Calls</TableHead>
                  <TableHead className="h-9 px-3 text-xs">Tools</TableHead>
                  <TableHead className="h-9 px-3 text-xs">Input Tokens</TableHead>
                  <TableHead className="h-9 px-3 text-xs">Output Tokens</TableHead>
                  <TableHead className="h-9 px-3 text-xs">Model</TableHead>
                  <TableHead className="h-9 px-3 text-xs">Started</TableHead>
                  <TableHead className="h-9 px-3 text-xs">Duration</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((s) => (
                  <TableRow key={s.session_id} className="cursor-pointer" onClick={() => router.push(`/sessions/${s.session_id}`)}>
                    <TableCell className="px-3 py-2 font-mono text-xs">{s.session_id.slice(0, 12)}…</TableCell>
                    <TableCell className="px-3 py-2 text-xs">{s.service_name}</TableCell>
                    <TableCell className="px-3 py-2 text-xs">{s.prompt_count}</TableCell>
                    <TableCell className="px-3 py-2 text-xs">{s.api_request_count}</TableCell>
                    <TableCell className="px-3 py-2 text-xs">{s.tool_result_count}</TableCell>
                    <TableCell className="px-3 py-2 text-xs">{s.total_input_tokens.toLocaleString()}</TableCell>
                    <TableCell className="px-3 py-2 text-xs">{s.total_output_tokens.toLocaleString()}</TableCell>
                    <TableCell className="px-3 py-2 text-xs text-muted-foreground">{s.model || "—"}</TableCell>
                    <TableCell className="px-3 py-2 text-xs text-muted-foreground">
                      {formatDistanceToNow(new Date(s.first_event_time), { addSuffix: true })}
                    </TableCell>
                    <TableCell className="px-3 py-2 text-xs">{formatDuration(s.first_event_time, s.last_event_time)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </DashboardContent>
    </DashboardShell>
  );
}
