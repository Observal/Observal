"use client";

import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Search,
  Puzzle,
  LayoutGrid,
  TableProperties,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useRegistryList } from "@/hooks/use-api";
import type { RegistryType } from "@/lib/api";
import type { RegistryItem } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/layouts/page-header";
import {
  TableSkeleton,
  CardSkeleton,
} from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { StatusBadge } from "@/components/registry/status-badge";
import { ComponentCard } from "@/components/registry/component-card";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type Column,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { cn } from "@/lib/utils";

const TYPES: { value: RegistryType; label: string }[] = [
  { value: "mcps", label: "MCPs" },
  { value: "skills", label: "Skills" },
  { value: "hooks", label: "Hooks" },
  { value: "prompts", label: "Prompts" },
  { value: "sandboxes", label: "Sandboxes" },
];

const TYPE_LABELS: Record<string, string> = {
  mcps: "MCP",
  skills: "Skill",
  hooks: "Hook",
  prompts: "Prompt",
  sandboxes: "Sandbox",
};

type ViewMode = "table" | "grid";

function SortIcon({ column }: { column: Column<RegistryItem> }) {
  const sorted = column.getIsSorted();
  if (sorted === "asc") return <ArrowUp className="h-3 w-3" />;
  if (sorted === "desc") return <ArrowDown className="h-3 w-3" />;
  return <ArrowUpDown className="h-3 w-3 opacity-40" />;
}

function makeColumns(activeType: RegistryType): ColumnDef<RegistryItem>[] {
  return [
    {
      accessorKey: "name",
      header: ({ column }) => (
        <button
          className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        >
          Name
          <SortIcon column={column} />
        </button>
      ),
      cell: ({ row }) => (
        <div className="min-w-[160px]">
          <Link
            href={`/components/${row.original.id}?type=${activeType}`}
            className="font-medium text-sm hover:underline underline-offset-4"
          >
            {row.original.name}
          </Link>
          {row.original.description && (
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1 max-w-xs">
              {row.original.description}
            </p>
          )}
        </div>
      ),
    },
    {
      accessorKey: "version",
      header: "Version",
      cell: ({ row }) => (
        <span className="text-muted-foreground text-sm font-mono">
          {(row.original.version as string | undefined) ?? "-"}
        </span>
      ),
    },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ row }) =>
        row.original.status ? (
          <StatusBadge status={row.original.status} />
        ) : (
          <span className="text-muted-foreground">-</span>
        ),
    },
    {
      accessorKey: "updated_at",
      header: ({ column }) => (
        <button
          className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        >
          Updated
          <SortIcon column={column} />
        </button>
      ),
      cell: ({ row }) => (
        <span className="text-muted-foreground text-sm">
          {row.original.updated_at
            ? new Date(row.original.updated_at).toLocaleDateString()
            : "-"}
        </span>
      ),
    },
  ];
}

export default function ComponentsPage() {
  const router = useRouter();
  const [activeType, setActiveType] = useState<RegistryType>("mcps");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [view, setView] = useState<ViewMode>("table");
  const [sorting, setSorting] = useState<SortingState>([]);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    timerRef.current = setTimeout(() => {
      setDebouncedSearch(search);
    }, 300);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [search]);

  const { data, isLoading, isError, error, refetch } = useRegistryList(
    activeType,
    debouncedSearch ? { search: debouncedSearch } : undefined,
  );

  const items = useMemo(() => data ?? [], [data]);

  const columns = useMemo(() => makeColumns(activeType), [activeType]);

  const table = useReactTable({
    data: items,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const handleRowClick = useCallback(
    (id: string) => {
      router.push(`/components/${id}?type=${activeType}`);
    },
    [router, activeType],
  );

  return (
    <>
      <PageHeader
        title="Components"
        breadcrumbs={[
          { label: "Registry", href: "/" },
          { label: "Components" },
        ]}
      />

      <div className="p-6 lg:p-8 w-full max-w-[1200px] mx-auto space-y-5">
        {/* Toolbar */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative max-w-sm flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder={`Search ${TYPE_LABELS[activeType] ?? activeType}s...`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9"
            />
          </div>
          <div className="flex items-center border border-border rounded-md overflow-hidden ml-auto">
            <Button
              variant={view === "table" ? "secondary" : "ghost"}
              size="sm"
              className="rounded-none h-8 px-2.5"
              onClick={() => setView("table")}
              aria-label="Table view"
            >
              <TableProperties className="h-4 w-4" />
            </Button>
            <Button
              variant={view === "grid" ? "secondary" : "ghost"}
              size="sm"
              className="rounded-none h-8 px-2.5"
              onClick={() => setView("grid")}
              aria-label="Grid view"
            >
              <LayoutGrid className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Type filter tabs */}
        <div className="flex items-center gap-1 border-b border-border">
          {TYPES.map((t) => (
            <button
              key={t.value}
              onClick={() => {
                setActiveType(t.value);
                setSorting([]);
              }}
              className={cn(
                "relative px-3 py-2 text-sm font-medium transition-colors hover:text-foreground",
                activeType === t.value
                  ? "text-foreground"
                  : "text-muted-foreground",
              )}
            >
              {t.label}
              {activeType === t.value && (
                <span className="absolute inset-x-0 -bottom-px h-0.5 bg-primary-accent" />
              )}
            </button>
          ))}
        </div>

        {/* Content */}
        {isLoading ? (
          view === "table" ? (
            <TableSkeleton rows={8} cols={4} />
          ) : (
            <CardSkeleton count={6} columns={3} />
          )
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={Puzzle}
            title={`No ${TYPE_LABELS[activeType] ?? activeType}s found`}
            description={
              debouncedSearch
                ? `No ${TYPE_LABELS[activeType] ?? activeType}s match "${debouncedSearch}". Try a different search.`
                : `No ${TYPE_LABELS[activeType] ?? activeType}s have been registered yet.`
            }
            actionLabel="Back to Registry"
            actionHref="/"
          />
        ) : view === "table" ? (
          <div className="overflow-x-auto animate-in">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHead key={header.id} className="text-xs">
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows.map((row) => (
                  <TableRow
                    key={row.id}
                    className="cursor-pointer hover:bg-accent/40 transition-colors"
                    onClick={() => handleRowClick(row.original.id)}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext(),
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <div
            className="grid gap-4 animate-in"
            style={{
              gridTemplateColumns:
                "repeat(auto-fill, minmax(min(320px, 100%), 1fr))",
            }}
          >
            {items.map((item: RegistryItem, i: number) => (
              <ComponentCard
                key={item.id}
                id={item.id}
                name={item.name}
                type={activeType}
                description={item.description}
                version={item.version as string | undefined}
                status={item.status}
                git_url={item.git_url as string | undefined}
                className={`animate-in stagger-${Math.min(i + 1, 5)}`}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
