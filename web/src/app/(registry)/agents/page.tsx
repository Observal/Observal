"use client";

import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import {
  Search,
  Bot,
  LayoutGrid,
  TableProperties,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Trash2,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { useRegistryList, useWhoami } from "@/hooks/use-api";
import { registry, getUserRole } from "@/lib/api";
import { hasMinRole } from "@/hooks/use-role-guard";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton, CardSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { StatusBadge } from "@/components/registry/status-badge";
import { AgentCard } from "@/components/registry/agent-card";
import { compactNumber } from "@/lib/utils";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type Column,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import type { RegistryItem } from "@/lib/types";

type ViewMode = "table" | "grid";

function DeleteAgentButton({ agent }: { agent: RegistryItem }) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const qc = useQueryClient();
  const { data: whoami } = useWhoami();
  const isAdmin = hasMinRole(getUserRole(), "admin");
  const canDelete = isAdmin || (whoami?.id && agent.created_by && whoami.id === String(agent.created_by));

  async function handleDelete(e: React.MouseEvent) {
    e.stopPropagation();
    setDeleting(true);
    try {
      await registry.delete("agents", agent.id);
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success("Agent deleted");
      setConfirmOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete");
      setDeleting(false);
    }
  }

  if (!canDelete) return null;

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
        onClick={(e) => {
          e.stopPropagation();
          setConfirmOpen(true);
        }}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </Button>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent onClick={(e) => e.stopPropagation()}>
          <DialogHeader>
            <DialogTitle>Delete {agent.name}?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This will permanently delete this agent. This action cannot be undone.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function SortIcon({ column }: { column: Column<RegistryItem> }) {
  const sorted = column.getIsSorted();
  if (sorted === "asc") return <ArrowUp className="h-3 w-3" />;
  if (sorted === "desc") return <ArrowDown className="h-3 w-3" />;
  return <ArrowUpDown className="h-3 w-3 opacity-40" />;
}

const columns: ColumnDef<RegistryItem>[] = [
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
          href={`/agents/${row.original.id}`}
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
    accessorKey: "download_count",
    header: ({ column }) => (
      <button
        className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
      >
        Downloads
        <SortIcon column={column} />
      </button>
    ),
    cell: ({ row }) => (
      <span className="text-muted-foreground text-sm font-mono">
        {row.original.download_count != null
          ? compactNumber(row.original.download_count as number)
          : "-"}
      </span>
    ),
  },
  {
    accessorKey: "average_rating",
    header: ({ column }) => (
      <button
        className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
      >
        Rating
        <SortIcon column={column} />
      </button>
    ),
    cell: ({ row }) => (
      <span className="text-muted-foreground text-sm">
        {row.original.average_rating != null
          ? (row.original.average_rating as number).toFixed(1)
          : "-"}
      </span>
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
  {
    id: "actions",
    header: "",
    cell: ({ row }) => <DeleteAgentButton agent={row.original} />,
  },
];

export default function AgentListPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const initialSearch = searchParams.get("search") ?? "";
  const [search, setSearch] = useState(initialSearch);
  const [debouncedSearch, setDebouncedSearch] = useState(initialSearch);
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

  const {
    data: agents,
    isLoading,
    isError,
    error,
    refetch,
  } = useRegistryList(
    "agents",
    debouncedSearch ? { search: debouncedSearch } : undefined,
  );

  const filtered = useMemo(() => agents ?? [], [agents]);

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const handleRowClick = useCallback(
    (id: string) => {
      router.push(`/agents/${id}`);
    },
    [router],
  );

  return (
    <>
      <PageHeader
        title="Agents"
        breadcrumbs={[
          { label: "Registry", href: "/" },
          { label: "Agents" },
        ]}
      />

      <div className="p-6 lg:p-8 w-full max-w-[1200px] mx-auto space-y-5">
        {/* Toolbar */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative max-w-sm flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search agents..."
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

        {/* Content */}
        {isLoading ? (
          view === "table" ? (
            <TableSkeleton rows={8} cols={6} />
          ) : (
            <CardSkeleton count={6} columns={3} />
          )
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={Bot}
            title="No agents published yet"
            description={
              debouncedSearch
                ? `No agents match "${debouncedSearch}". Try a different search term.`
                : "No agents have been submitted yet. Be the first to publish one."
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
            {filtered.map((agent: RegistryItem, i: number) => (
              <AgentCard
                key={agent.id}
                id={agent.id}
                name={agent.name}
                description={agent.description as string | undefined}
                owner={agent.owner as string | undefined}
                version={agent.version as string | undefined}
                downloads={agent.download_count as number | undefined}
                score={(agent.average_rating as number | null) ?? undefined}
                status={agent.status}
                component_count={agent.component_count as number | undefined}
                className={`animate-in stagger-${Math.min(i + 1, 5)}`}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
