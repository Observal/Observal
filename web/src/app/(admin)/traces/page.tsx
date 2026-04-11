"use client";

import { useState, useMemo, useCallback } from "react";
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
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

interface SessionRow {
  session_id: string;
  service_name: string;
  first_event_time?: string;
  prompt_count?: number;
}

const columns: ColumnDef<SessionRow>[] = [
  {
    accessorKey: "session_id",
    header: "Session ID",
    cell: ({ row }) => (
      <Link
        href={`/traces/${row.original.session_id}`}
        className="font-[family-name:var(--font-mono)] text-xs hover:text-primary-accent transition-colors"
      >
        {row.original.session_id.slice(0, 16)}...
      </Link>
    ),
  },
  {
    accessorKey: "service_name",
    header: "Service",
    cell: ({ row }) => (
      <span className="text-sm">{row.original.service_name || "-"}</span>
    ),
  },
  {
    accessorKey: "prompt_count",
    header: "Events",
    cell: ({ row }) => (
      <span className="text-xs text-muted-foreground font-[family-name:var(--font-mono)] tabular-nums">
        {row.original.prompt_count ?? "-"}
      </span>
    ),
  },
  {
    accessorKey: "first_event_time",
    header: "Timestamp",
    cell: ({ row }) => {
      const t = row.original.first_event_time;
      return (
        <span className="text-xs text-muted-foreground tabular-nums">
          {t ? new Date(t).toLocaleString() : "-"}
        </span>
      );
    },
  },
];

function SortIcon({ sorted }: { sorted: false | "asc" | "desc" }) {
  if (sorted === "asc") return <ArrowUp className="h-3 w-3" />;
  if (sorted === "desc") return <ArrowDown className="h-3 w-3" />;
  return <ArrowUpDown className="h-3 w-3 opacity-40" />;
}

export default function TracesPage() {
  const { data: sessions, isLoading, isError, error, refetch } = useOtelSessions();
  const router = useRouter();

  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");

  const data = useMemo(() => (sessions ?? []) as SessionRow[], [sessions]);

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
  const handleSearch = useCallback(
    (() => {
      let timeout: ReturnType<typeof setTimeout>;
      return (value: string) => {
        setSearchValue(value);
        clearTimeout(timeout);
        timeout = setTimeout(() => setGlobalFilter(value), 300);
      };
    })(),
    [],
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
      <div className="p-6 max-w-6xl mx-auto space-y-4">
        {isLoading ? (
          <TableSkeleton rows={8} cols={4} />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : (sessions ?? []).length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No traces yet"
            description="Traces will appear here once telemetry data is collected from your agents."
          />
        ) : (
          <div className="animate-in space-y-3">
            {/* Search */}
            <div className="relative max-w-sm">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Search sessions, services..."
                value={searchValue}
                onChange={(e) => handleSearch(e.target.value)}
                className="pl-8 h-8 text-sm"
              />
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
                          className="h-8 text-xs cursor-pointer select-none hover:text-foreground transition-colors"
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
                        No matching traces.
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
                          <TableCell key={cell.id} className="py-1.5">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>

            <p className="text-xs text-muted-foreground">
              {table.getFilteredRowModel().rows.length} trace{table.getFilteredRowModel().rows.length !== 1 ? "s" : ""}
            </p>
          </div>
        )}
      </div>
    </>
  );
}
