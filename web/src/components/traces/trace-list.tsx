// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState } from "react";
import { useRouter } from "@tanstack/react-router";
import { useTraces } from "@/hooks/use-api";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { StatusBadge } from "@/components/registry/status-badge";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryError } from "@/components/dashboard/query-error";
import { useIdes } from "@/hooks/use-ides";
import { ListTree } from "lucide-react";

const IDE_BADGE_STYLES: Record<string, string> = {
  "claude-code": "bg-light-yellow text-dark-yellow",
  kiro: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400",
  cursor: "bg-cyan-100 text-cyan-800 dark:bg-cyan-900/30 dark:text-cyan-400",
  "gemini-cli": "bg-light-red text-dark-red",
  codex: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-400",
  copilot: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400",
  "copilot-cli": "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400",
  "GitHub Copilot": "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400",
};

const IDE_LABELS: Record<string, string> = {
  "claude-code": "Claude Code",
  kiro: "Kiro",
  cursor: "Cursor",
  "gemini-cli": "Gemini CLI",
  codex: "Codex",
  copilot: "Copilot",
  "copilot-cli": "Copilot CLI",
  "GitHub Copilot": "Copilot CLI",
};

const TRACE_TYPES = [
  "all",
  "mcp",
  "agent",
  "tool",
  "skill",
  "hook",
  "prompt",
  "sandbox",
  "graphrag",
];
const IDES_FALLBACK = [
  "all",
  "claude-code",
  "kiro",
  "cursor",
  "gemini-cli",
  "codex",
  "copilot",
  "copilot-cli",
];

export function TraceList() {
  const router = useRouter();
  const { data: ideList } = useIdes();
  const [search, setSearch] = useState("");
  const [traceType, setTraceType] = useState("all");
  const [ide, setIde] = useState("all");

  const ideOptions = ideList ? ["all", ...ideList.map((i) => i.name)] : IDES_FALLBACK;
  const ideDisplayNames: Record<string, string> = Object.fromEntries(
    (ideList ?? []).map((i) => [i.name, i.display_name]),
  );

  const filters: Record<string, unknown> = {};
  if (traceType !== "all") filters.trace_type = traceType;
  if (ide !== "all") filters.ide = ide;

  const { data: traces, isLoading, isError, error, refetch } = useTraces(
    Object.keys(filters).length ? filters : undefined,
  );

  const items = traces as Record<string, unknown>[] | undefined;
  const filtered = items?.filter(
    (t) =>
      !search ||
      (t.name as string)?.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="flex flex-col gap-3">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search by name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 max-w-xs text-sm"
        />
        <Select value={traceType} onValueChange={setTraceType}>
          <SelectTrigger className="h-8 w-[140px] text-sm">
            <SelectValue placeholder="Trace type" />
          </SelectTrigger>
          <SelectContent>
            {TRACE_TYPES.map((t) => (
              <SelectItem key={t} value={t} className="text-sm">
                {t === "all" ? "All types" : t}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={ide} onValueChange={setIde}>
          <SelectTrigger className="h-8 w-[140px] text-sm">
            <SelectValue placeholder="IDE" />
          </SelectTrigger>
          <SelectContent>
            {ideOptions.map((i) => (
              <SelectItem key={i} value={i} className="text-sm">
                {i === "all" ? "All IDEs" : (ideDisplayNames[i] || IDE_LABELS[i] || i)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      {isError ? (
        <QueryError message={error?.message} onRetry={refetch} />
      ) : isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-8 w-full" />
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : !filtered?.length ? (
        <div className="flex flex-col items-center justify-center rounded-md border border-dashed py-16">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-muted">
            <ListTree className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="mt-3 text-sm font-medium">No traces yet</p>
          <p className="mt-1 max-w-sm text-center text-xs text-muted-foreground">
            Traces are created automatically when tools are invoked through
            Observal. Install an MCP server or agent to start collecting traces.
          </p>
        </div>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="h-9 px-3 text-xs">Trace ID</TableHead>
                <TableHead className="h-9 px-3 text-xs">Type</TableHead>
                <TableHead className="h-9 px-3 text-xs">Name</TableHead>
                <TableHead className="h-9 px-3 text-xs">IDE</TableHead>
                <TableHead className="h-9 px-3 text-xs">Start Time</TableHead>
                <TableHead className="h-9 px-3 text-xs">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((t) => {
                const traceId = (t.traceId ?? t.trace_id ?? t.id) as string;
                const metrics = t.metrics as Record<string, unknown> | undefined;
                const status = (t.status as string) ?? (metrics?.errorCount ? "error" : "success");
                return (
                  <TableRow
                    key={traceId}
                    className="cursor-pointer"
                    onClick={() => router.navigate({ to: "/traces/$traceId", params: { traceId } })}
                  >
                    <TableCell className="px-3 py-2 font-mono text-xs">
                      {traceId?.slice(0, 12)}…
                    </TableCell>
                    <TableCell className="px-3 py-2">
                      <Badge variant="outline" className="text-xs">
                        {(t.trace_type ?? t.traceType ?? "") as string}
                      </Badge>
                    </TableCell>
                    <TableCell className="px-3 py-2 text-sm">
                      {(t.name ?? "—") as string}
                    </TableCell>
                    <TableCell className="px-3 py-2">
                      {(() => {
                        const ideVal = (t.ide ?? "") as string;
                        const style = IDE_BADGE_STYLES[ideVal];
                        const label = IDE_LABELS[ideVal] || ideVal || "—";
                        return style ? (
                          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${style}`}>
                            {label}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">{label}</span>
                        );
                      })()}
                    </TableCell>
                    <TableCell className="px-3 py-2 text-xs text-muted-foreground">
                      {t.startTime || t.start_time
                        ? new Date(
                            (t.startTime ?? t.start_time) as string,
                          ).toLocaleString()
                        : "—"}
                    </TableCell>
                    <TableCell className="px-3 py-2">
                      <StatusBadge status={status} />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
