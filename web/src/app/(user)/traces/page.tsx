"use client";

import { useState, useMemo, useCallback, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity,
  Search,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  BarChart3,
} from "lucide-react";
import {
  useOtelSessions,
  useOtelSessionsSummary,
  useSessionSubscription,
} from "@/hooks/use-api";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import type { OtelSession } from "@/lib/types";

// ── Helpers ──────────────────────────────────────────────────────────

function isKiroSession(row: OtelSession): boolean {
  return row.service_name === "kiro" || row.session_id.startsWith("kiro-");
}

function fmtTokens(n: number | string | undefined): string {
  if (n == null) return "0";
  const num = typeof n === "string" ? parseInt(n, 10) : n;
  if (isNaN(num)) return "0";
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`;
  return `${num}`;
}

function fmtCredits(c: string | undefined): string {
  if (!c) return "0.00";
  const num = parseFloat(c);
  if (isNaN(num)) return "0.00";
  return num < 0.01 && num > 0 ? num.toFixed(4) : num.toFixed(2);
}

function fmtDuration(first?: string, last?: string): string {
  if (!first || !last) return "\u2013";
  const ms = toDate(last).getTime() - toDate(first).getTime();
  if (ms < 0) return "\u2013";
  const mins = Math.floor(ms / 60_000);
  const hours = Math.floor(mins / 60);
  if (hours > 0) return `${hours}h ${String(mins % 60).padStart(2, "0")}m`;
  if (mins > 0) return `${mins}m`;
  return "< 1m";
}

function toDate(ts: string): Date {
  if (ts.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(ts)) return new Date(ts);
  return new Date(ts + "Z");
}

function relTime(ts?: string): string {
  if (!ts) return "\u2013";
  const ms = Date.now() - toDate(ts).getTime();
  if (ms < 0) return "just now";
  const mins = Math.floor(ms / 60_000);
  const hours = Math.floor(ms / 3_600_000);
  const days = Math.floor(ms / 86_400_000);
  if (days > 0) return `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  if (mins > 0) return `${mins}m ago`;
  return "just now";
}

function absTime(ts?: string): string {
  if (!ts) return "";
  return toDate(ts).toLocaleString();
}

function shortModel(raw?: string): string {
  if (!raw) return "";
  return raw
    .replace("claude-", "")
    .replace("anthropic.", "")
    .replace(/-\d{8}$/, "");
}

function derivePlatform(row: OtelSession): string {
  if (row.platform) return row.platform;
  return isKiroSession(row) ? "Kiro" : "Claude Code";
}

function sessionLabel(row: OtelSession): string {
  const model = shortModel(row.model);
  const count = row.prompt_count ?? 0;
  const suffix = count === 1 ? "prompt" : "prompts";
  if (model) return `${model} \u00b7 ${count} ${suffix}`;
  return `${count} ${suffix}`;
}

// ── Column Definitions ───────────────────────────────────────────────

const columns: ColumnDef<OtelSession>[] = [
  {
    accessorKey: "session_id",
    header: "Session",
    cell: ({ row }) => (
      <Link
        href={`/traces/${row.original.session_id}`}
        className="text-[13px] font-medium text-foreground/90 hover:text-foreground transition-colors whitespace-nowrap"
        onClick={(e) => e.stopPropagation()}
      >
        {sessionLabel(row.original)}
      </Link>
    ),
  },
  {
    accessorKey: "user_name",
    header: "User",
    cell: ({ row }) => (
      <span className="text-[13px] text-muted-foreground whitespace-nowrap">
        {row.original.user_name || "\u2014"}
      </span>
    ),
  },
  {
    id: "platform",
    accessorFn: (row) => derivePlatform(row),
    header: "Platform",
    cell: ({ row }) => (
      <span className="text-[13px] font-medium text-foreground/80 whitespace-nowrap">
        {derivePlatform(row.original)}
      </span>
    ),
  },
  {
    id: "tokens",
    header: "Tokens",
    accessorFn: (row) => row.total_input_tokens ?? 0,
    cell: ({ row }) => {
      const r = row.original;
      if (isKiroSession(r)) {
        return (
          <span className="text-[13px] font-mono tabular-nums text-orange-400">
            {fmtCredits(r.credits)} cr
          </span>
        );
      }
      const inp = fmtTokens(r.total_input_tokens);
      const out = fmtTokens(r.total_output_tokens);
      return (
        <span
          className="text-[13px] font-mono tabular-nums"
          title={`In: ${r.total_input_tokens?.toLocaleString() ?? 0} · Out: ${r.total_output_tokens?.toLocaleString() ?? 0}`}
        >
          <span className="text-emerald-400">{inp}</span>
          <span className="text-muted-foreground/50"> / </span>
          <span className="text-blue-400">{out}</span>
        </span>
      );
    },
  },
  {
    accessorKey: "tool_result_count",
    header: "Tools",
    cell: ({ row }) => (
      <span className="text-[13px] font-mono tabular-nums text-muted-foreground">
        {row.original.tool_result_count ?? 0}
      </span>
    ),
  },
  {
    id: "duration",
    header: "Duration",
    accessorFn: (row) => {
      if (!row.first_event_time || !row.last_event_time) return 0;
      return toDate(row.last_event_time).getTime() - toDate(row.first_event_time).getTime();
    },
    cell: ({ row }) => (
      <span className="text-[13px] text-muted-foreground tabular-nums whitespace-nowrap">
        {fmtDuration(row.original.first_event_time, row.original.last_event_time)}
      </span>
    ),
  },
  {
    accessorKey: "first_event_time",
    header: "Started",
    cell: ({ row }) => (
      <span
        className="text-[13px] text-muted-foreground tabular-nums whitespace-nowrap"
        title={absTime(row.original.first_event_time)}
      >
        {relTime(row.original.first_event_time)}
      </span>
    ),
    sortingFn: (a, b) => {
      const ta = a.original.first_event_time ? toDate(a.original.first_event_time).getTime() : 0;
      const tb = b.original.first_event_time ? toDate(b.original.first_event_time).getTime() : 0;
      return ta - tb;
    },
  },
  {
    id: "score",
    header: "Score",
    cell: () => <span className="text-[13px] text-muted-foreground">{"\u2014"}</span>,
    enableSorting: false,
  },
];

// ── Sort Icon ────────────────────────────────────────────────────────

function SortIcon({ sorted }: { sorted: false | "asc" | "desc" }) {
  if (sorted === "asc") return <ArrowUp className="h-3 w-3" />;
  if (sorted === "desc") return <ArrowDown className="h-3 w-3" />;
  return <ArrowUpDown className="h-3 w-3 opacity-25" />;
}

// ── Time Filter Options ──────────────────────────────────────────────

const TIME_OPTIONS = [
  { label: "All time", value: "all" },
  { label: "Today", value: "1" },
  { label: "7 days", value: "7" },
  { label: "30 days", value: "30" },
];

// ── Page ─────────────────────────────────────────────────────────────

export default function TracesPage() {
  const [tab, setTab] = useState<"all" | "active">("all");
  const [platform, setPlatform] = useState("all");
  const [timeRange, setTimeRange] = useState("all");
  const router = useRouter();

  const daysParam = timeRange !== "all" ? parseInt(timeRange, 10) : undefined;
  const platformParam = platform !== "all" ? platform : undefined;

  const { data: sessions, isLoading, isError, error, refetch } = useOtelSessions({
    refetchInterval: 30_000,
    platform: platformParam,
    days: daysParam,
  });
  const { data: summary } = useOtelSessionsSummary();
  useSessionSubscription();

  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");

  const allSessions = useMemo(() => (sessions ?? []) as OtelSession[], [sessions]);
  const activeCount = useMemo(() => allSessions.filter((s) => s.is_active).length, [allSessions]);
  const data = useMemo(
    () => (tab === "active" ? allSessions.filter((s) => s.is_active) : allSessions),
    [allSessions, tab],
  );

  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const [searchValue, setSearchValue] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const handleSearch = useCallback(
    (value: string) => {
      setSearchValue(value);
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => setGlobalFilter(value), 300);
    },
    [setGlobalFilter],
  );

  const todaySessions = summary?.today_sessions ?? allSessions.length;

  return (
    <>
      <PageHeader
        title="Traces"
        breadcrumbs={[{ label: "Dashboard", href: "/dashboard" }, { label: "Traces" }]}
      />
      <div className="p-6 w-full mx-auto space-y-5">
        {isLoading ? (
          <TableSkeleton rows={8} cols={8} />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : allSessions.length === 0 && !platformParam && !daysParam ? (
          <EmptyState
            icon={Activity}
            title="No sessions yet"
            description="Sessions will appear here once telemetry data is collected from your IDE."
          />
        ) : (
          <div className="animate-in space-y-5">
            {/* ── Summary ── */}
            <div className="flex items-center gap-2.5 text-sm text-muted-foreground">
              <BarChart3 className="h-4 w-4 text-foreground/50" />
              <span>
                <span className="font-semibold text-foreground tabular-nums">{todaySessions}</span>
                {" "}session{todaySessions !== 1 ? "s" : ""} today
              </span>
            </div>

            {/* ── Toolbar ── */}
            <div className="flex items-center gap-3 flex-wrap">
              <Tabs value={tab} onValueChange={(v) => setTab(v as "all" | "active")}>
                <TabsList>
                  <TabsTrigger value="all">
                    All
                    <span className="ml-1.5 text-xs text-muted-foreground tabular-nums">
                      {allSessions.length}
                    </span>
                  </TabsTrigger>
                  <TabsTrigger value="active" className="gap-1.5">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
                    </span>
                    Active
                    {activeCount > 0 && (
                      <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px] font-semibold">
                        {activeCount}
                      </Badge>
                    )}
                  </TabsTrigger>
                </TabsList>
              </Tabs>

              <Select value={platform} onValueChange={setPlatform}>
                <SelectTrigger className="w-40 h-9 text-sm">
                  <SelectValue placeholder="All platforms" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All platforms</SelectItem>
                  <SelectItem value="claude-code">Claude Code</SelectItem>
                  <SelectItem value="kiro">Kiro</SelectItem>
                </SelectContent>
              </Select>

              <Select value={timeRange} onValueChange={setTimeRange}>
                <SelectTrigger className="w-32 h-9 text-sm">
                  <SelectValue placeholder="All time" />
                </SelectTrigger>
                <SelectContent>
                  {TIME_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <div className="relative max-w-xs flex-1 ml-auto">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Search sessions..."
                  value={searchValue}
                  onChange={(e) => handleSearch(e.target.value)}
                  className="pl-8 h-9 text-sm"
                />
              </div>
            </div>

            {/* ── Table ── */}
            <div className="rounded-lg border border-border overflow-hidden">
              <Table>
                <TableHeader>
                  {table.getHeaderGroups().map((hg) => (
                    <TableRow key={hg.id} className="hover:bg-transparent bg-muted/40 border-b border-border">
                      {hg.headers.map((header) => (
                        <TableHead
                          key={header.id}
                          className="h-11 px-5 text-center cursor-pointer select-none hover:text-foreground transition-colors"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          <span className="inline-flex items-center justify-center gap-1 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            <SortIcon sorted={header.column.getIsSorted()} />
                          </span>
                        </TableHead>
                      ))}
                    </TableRow>
                  ))}
                </TableHeader>
                <TableBody>
                  {table.getRowModel().rows.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={columns.length} className="h-32 text-center text-sm text-muted-foreground">
                        No matching sessions.
                      </TableCell>
                    </TableRow>
                  ) : (
                    table.getRowModel().rows.map((row, idx) => {
                      const active = row.original.is_active;
                      return (
                        <TableRow
                          key={row.id}
                          className={`relative cursor-pointer transition-colors hover:bg-muted/50 border-b border-border/50 ${
                            idx % 2 === 1 ? "bg-muted/15" : ""
                          }`}
                          onClick={() => router.push(`/traces/${row.original.session_id}`)}
                        >
                          {row.getVisibleCells().map((cell, cellIdx) => (
                            <TableCell key={cell.id} className={`py-4 px-5 text-center ${cellIdx === 0 ? "relative" : ""}`}>
                              {cellIdx === 0 && active && (
                                <span className="absolute inset-y-0 left-0 w-[3px] bg-green-500 rounded-r-sm" aria-hidden="true" />
                              )}
                              {flexRender(cell.column.columnDef.cell, cell.getContext())}
                            </TableCell>
                          ))}
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            </div>

            {/* ── Footer ── */}
            <p className="text-xs text-muted-foreground/70">
              Showing {table.getFilteredRowModel().rows.length} of {allSessions.length} session{allSessions.length !== 1 ? "s" : ""}
            </p>
          </div>
        )}
      </div>
    </>
  );
}
