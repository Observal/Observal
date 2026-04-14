"use client";

import { useState, useMemo, useCallback, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Activity, Search, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { useOtelSessions } from "@/hooks/use-api";
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
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

interface SessionRow {
  session_id: string;
  service_name: string;
  is_active?: boolean;
  first_event_time?: string;
  last_event_time?: string;
  prompt_count?: number;
  api_request_count?: number;
  tool_result_count?: number;
  total_input_tokens?: number;
  total_output_tokens?: number;
  total_cache_read_tokens?: number;
  model?: string;
  user_id?: string;
  terminal_type?: string;
  credits?: string;
  tools_used?: string;
}

function isKiroSession(row: SessionRow): boolean {
  return row.service_name === "kiro-cli" || row.session_id.startsWith("kiro-");
}

function formatCredits(c: string | undefined): string {
  if (!c) return "-";
  const num = parseFloat(c);
  if (isNaN(num)) return "-";
  return num < 0.01 ? num.toFixed(4) : num.toFixed(2);
}

function formatTokens(n: number | string | undefined): string {
  if (n == null) return "-";
  const num = typeof n === "string" ? parseInt(n, 10) : n;
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`;
  return `${num}`;
}

const columns: ColumnDef<SessionRow>[] = [
  {
    accessorKey: "session_id",
    header: "Session",
    cell: ({ row }) => (
      <div className="flex items-center gap-2">
        {row.original.is_active && (
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
          </span>
        )}
        <Link
          href={`/traces/${row.original.session_id}`}
          className="font-[family-name:var(--font-mono)] text-sm hover:text-primary-accent transition-colors"
        >
          {row.original.session_id.slice(0, 12)}...
        </Link>
      </div>
    ),
  },
  {
    accessorKey: "model",
    header: "Model",
    cell: ({ row }) => {
      const m = row.original.model;
      return (
        <span className="text-sm font-medium">
          {m ? m.replace("claude-", "").replace("-20251001", "") : "-"}
        </span>
      );
    },
  },
  {
    accessorKey: "user_id",
    header: "User",
    cell: ({ row }) => {
      const uid = row.original.user_id;
      return (
        <span className="text-sm font-[family-name:var(--font-mono)] text-muted-foreground" title={uid}>
          {uid ? uid.slice(0, 8) + "\u2026" : "-"}
        </span>
      );
    },
  },
  {
    accessorKey: "terminal_type",
    header: "IDE",
    cell: ({ row }) => {
      const t = row.original.terminal_type;
      const label = t ? t.replace("wsl-", "WSL ") : "-";
      return <span className="text-sm">{label}</span>;
    },
  },
  {
    accessorKey: "total_input_tokens",
    header: "Tokens In",
    cell: ({ row }) => {
      if (isKiroSession(row.original)) {
        return (
          <span className="text-sm font-[family-name:var(--font-mono)] tabular-nums text-orange-500" title="Kiro credits">
            {formatCredits(row.original.credits)} cr
          </span>
        );
      }
      return (
        <span className="text-sm font-[family-name:var(--font-mono)] tabular-nums text-muted-foreground">
          {formatTokens(row.original.total_input_tokens)}
        </span>
      );
    },
  },
  {
    accessorKey: "api_request_count",
    header: "API Calls",
    cell: ({ row }) => (
      <span className="text-sm font-[family-name:var(--font-mono)] tabular-nums text-muted-foreground">
        {row.original.api_request_count ?? "-"}
      </span>
    ),
  },
  {
    accessorKey: "tool_result_count",
    header: "Tools",
    cell: ({ row }) => (
      <span className="text-sm font-[family-name:var(--font-mono)] tabular-nums text-muted-foreground">
        {row.original.tool_result_count ?? "-"}
      </span>
    ),
  },
  {
    accessorKey: "total_output_tokens",
    header: "Tokens Out",
    cell: ({ row }) => {
      if (isKiroSession(row.original)) {
        const tools = row.original.tools_used;
        return (
          <span className="text-sm text-muted-foreground truncate max-w-[200px]" title={tools}>
            {tools || "-"}
          </span>
        );
      }
      return (
        <span className="text-sm font-[family-name:var(--font-mono)] tabular-nums text-muted-foreground">
          {formatTokens(row.original.total_output_tokens)}
        </span>
      );
    },
  },
  {
    accessorKey: "first_event_time",
    header: "Time",
    cell: ({ row }) => {
      const t = row.original.first_event_time;
      return (
        <span className="text-sm text-muted-foreground tabular-nums">
          {t ? new Date(t).toLocaleString() : "-"}
        </span>
      );
    },
  },
];

function SortIcon({ sorted }: { sorted: false | "asc" | "desc" }) {
  if (sorted === "asc") return <ArrowUp className="h-4 w-4" />;
  if (sorted === "desc") return <ArrowDown className="h-4 w-4" />;
  return <ArrowUpDown className="h-4 w-4 opacity-40" />;
}

export default function TracesPage() {
  const [tab, setTab] = useState<"all" | "active">("all");
  const { data: sessions, isLoading, isError, error, refetch } = useOtelSessions({
    refetchInterval: tab === "active" ? 10_000 : false,
  });
  const router = useRouter();

  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");

  const allSessions = useMemo(() => (sessions ?? []) as SessionRow[], [sessions]);
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

  // Debounced search
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

  return (
    <>
      <PageHeader
        title="Traces"
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Traces" },
        ]}
      />
      <div className="p-6 w-full max-w-6xl mx-auto space-y-4">
        {isLoading ? (
          <TableSkeleton rows={8} cols={7} />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : allSessions.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No sessions yet"
            description="Sessions will appear here once telemetry data is collected from Claude Code."
          />
        ) : (
          <div className="animate-in space-y-3">
            {/* Tabs + Search */}
            <div className="flex items-center gap-4">
              <Tabs value={tab} onValueChange={(v) => setTab(v as "all" | "active")}>
                <TabsList>
                  <TabsTrigger value="all">
                    All
                    <span className="ml-1.5 text-xs text-muted-foreground tabular-nums">{allSessions.length}</span>
                  </TabsTrigger>
                  <TabsTrigger value="active" className="gap-1.5">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
                    </span>
                    Active
                    {activeCount > 0 && (
                      <Badge variant="secondary" className="ml-1 h-4 px-1 text-xs font-medium">
                        {activeCount}
                      </Badge>
                    )}
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              <div className="relative max-w-sm flex-1">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Search sessions, models..."
                  value={searchValue}
                  onChange={(e) => handleSearch(e.target.value)}
                  className="pl-8 h-9 text-sm"
                />
              </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto rounded-md border border-border">
              <Table>
                <TableHeader>
                  {table.getHeaderGroups().map((headerGroup) => (
                    <TableRow key={headerGroup.id} className="hover:bg-transparent">
                      {headerGroup.headers.map((header) => (
                        <TableHead
                          key={header.id}
                          className="h-10 text-sm cursor-pointer select-none hover:text-foreground transition-colors"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          <span className="flex items-center gap-1">
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
                      <TableCell colSpan={columns.length} className="h-24 text-center text-sm text-muted-foreground">
                        No matching sessions.
                      </TableCell>
                    </TableRow>
                  ) : (
                    table.getRowModel().rows.map((row) => (
                      <TableRow
                        key={row.id}
                        className="cursor-pointer hover:bg-muted/60 transition-colors"
                        onClick={() => router.push(`/traces/${row.original.session_id}`)}
                      >
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id} className="py-2.5 px-4">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>

            <p className="text-sm text-muted-foreground">
              {table.getFilteredRowModel().rows.length} session{table.getFilteredRowModel().rows.length !== 1 ? "s" : ""}
              {tab === "active" && " \u00b7 auto-refreshing every 10s"}
            </p>
          </div>
        )}
      </div>
    </>
  );
}
