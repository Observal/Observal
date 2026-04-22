"use client";

import { Suspense, useState, useEffect, useRef, useMemo, useCallback, useSyncExternalStore } from "react";
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
  Clock,
  Archive,
  ArchiveRestore,
  FileEdit,
  Send,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useRegistryList, useMyAgents, useWhoami, useArchiveAgent, useUnarchiveAgent, useSubmitDraft } from "@/hooks/use-api";
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

const roleSub = (cb: () => void) => {
  window.addEventListener("storage", cb);
  return () => window.removeEventListener("storage", cb);
};

function DeleteAgentButton({ agent }: { agent: RegistryItem }) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const qc = useQueryClient();
  const { data: whoami } = useWhoami();
  const isAdmin = useSyncExternalStore(roleSub, () => hasMinRole(getUserRole(), "admin"), () => false);
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
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
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
          </TooltipTrigger>
          <TooltipContent>Delete</TooltipContent>
        </Tooltip>
      </TooltipProvider>

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

function ArchiveAgentButton({ agent }: { agent: RegistryItem }) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const isAdmin = useSyncExternalStore(roleSub, () => hasMinRole(getUserRole(), "admin"), () => false);
  const archiveMutation = useArchiveAgent();

  if (!isAdmin || agent.status === "archived") return null;

  return (
    <>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-muted-foreground hover:text-orange-600"
              onClick={(e) => {
                e.stopPropagation();
                setConfirmOpen(true);
              }}
            >
              <Archive className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Archive</TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent onClick={(e) => e.stopPropagation()}>
          <DialogHeader>
            <DialogTitle>Archive Agent</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This will hide the agent from the registry. The agent data will be preserved.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button
              variant="destructive"
              onClick={(e) => {
                e.stopPropagation();
                archiveMutation.mutate(agent.id, {
                  onSuccess: () => setConfirmOpen(false),
                });
              }}
              disabled={archiveMutation.isPending}
            >
              {archiveMutation.isPending ? "Archiving..." : "Archive"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function UnarchiveAgentButton({ agent }: { agent: RegistryItem }) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const isAdmin = useSyncExternalStore(roleSub, () => hasMinRole(getUserRole(), "admin"), () => false);
  const unarchiveMutation = useUnarchiveAgent();

  if (!isAdmin || agent.status !== "archived") return null;

  return (
    <>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-muted-foreground hover:text-green-600"
              onClick={(e) => {
                e.stopPropagation();
                setConfirmOpen(true);
              }}
            >
              <ArchiveRestore className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Restore</TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent onClick={(e) => e.stopPropagation()}>
          <DialogHeader>
            <DialogTitle>Restore Agent</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This will restore the agent to the public registry.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button
              onClick={(e) => {
                e.stopPropagation();
                unarchiveMutation.mutate(agent.id, {
                  onSuccess: () => setConfirmOpen(false),
                });
              }}
              disabled={unarchiveMutation.isPending}
            >
              {unarchiveMutation.isPending ? "Restoring..." : "Restore"}
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
        <div className="flex items-center gap-2">
          <Link
            href={`/agents/${row.original.id}`}
            className="font-medium text-sm hover:underline underline-offset-4"
          >
            {row.original.name}
          </Link>
          {row.original.status && row.original.status !== "active" && (
            <span className="inline-flex items-center gap-1 rounded-full bg-yellow-500/10 px-2 py-0.5 text-[10px] font-medium text-yellow-600 dark:text-yellow-400 ring-1 ring-yellow-500/20">
              <Clock className="h-2.5 w-2.5" />
              Pending Review
            </span>
          )}
        </div>
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
    cell: ({ row }) => {
      const status = row.original.status as string | undefined;
      const reason = row.original.rejection_reason as string | undefined;
      return status ? (
        <div>
          <StatusBadge status={status} />
          {status === "rejected" && reason && (
            <p className="text-xs text-destructive mt-0.5 line-clamp-2 max-w-[300px]" title={reason}>
              {reason}
            </p>
          )}
        </div>
      ) : (
        <span className="text-muted-foreground">-</span>
      );
    },
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
    cell: ({ row }) => (
      <div className="flex items-center gap-1">
        <ArchiveAgentButton agent={row.original} />
        <UnarchiveAgentButton agent={row.original} />
        <DeleteAgentButton agent={row.original} />
      </div>
    ),
  },
];

export default function AgentListPage() {
  return (
    <Suspense>
      <AgentListContent />
    </Suspense>
  );
}

function AgentListContent() {
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

  const { data: myAgents } = useMyAgents();
  const submitDraft = useSubmitDraft();
  const [draftsExpanded, setDraftsExpanded] = useState(true);
  const [deletingDraftId, setDeletingDraftId] = useState<string | null>(null);
  const qc = useQueryClient();

  const drafts = useMemo(() => {
    return (myAgents ?? []).filter((a) => a.status === "draft");
  }, [myAgents]);

  const { filtered, pendingCount } = useMemo(() => {
    const active = agents ?? [];
    const activeIds = new Set(active.map((a) => a.id));
    const pending = (myAgents ?? []).filter(
      (a) => a.status !== "active" && a.status !== "draft" && !activeIds.has(a.id),
    );
    return { filtered: [...pending, ...active], pendingCount: pending.length };
  }, [agents, myAgents]);

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

  function handleEditDraft(draft: RegistryItem) {
    router.push(`/agents/builder?draft=${draft.id}`);
  }

  async function handleDeleteDraft(id: string) {
    setDeletingDraftId(id);
    try {
      await registry.delete("agents", id);
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success("Draft deleted");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete draft");
    } finally {
      setDeletingDraftId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Agents"
        breadcrumbs={[
          { label: "Registry", href: "/" },
          { label: "Agents" },
        ]}
      />

      <div className="p-6 lg:p-8 w-full mx-auto space-y-5">
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

        {/* My Drafts */}
        {drafts.length > 0 && (
          <div className="rounded-lg border border-border bg-card">
            <button
              type="button"
              className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium hover:bg-accent/40 transition-colors rounded-t-lg"
              onClick={() => setDraftsExpanded((prev) => !prev)}
            >
              {draftsExpanded ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
              My Drafts
              <span className="ml-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-muted px-1.5 text-[11px] font-medium text-muted-foreground">
                {drafts.length}
              </span>
            </button>
            {draftsExpanded && (
              <div className="divide-y divide-border border-t">
                {drafts.map((draft) => (
                  <div key={draft.id} className="flex items-center gap-4 px-4 py-3">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{draft.name}</p>
                      {draft.description && (
                        <p className="truncate text-xs text-muted-foreground mt-0.5">
                          {draft.description}
                        </p>
                      )}
                      {draft.updated_at && (
                        <p className="text-[11px] text-muted-foreground mt-1">
                          Last updated {new Date(draft.updated_at).toLocaleDateString()}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => handleEditDraft(draft)}
                      >
                        <FileEdit className="mr-1 h-3 w-3" />
                        Edit
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        disabled={submitDraft.isPending}
                        onClick={() => submitDraft.mutate(draft.id)}
                      >
                        <Send className="mr-1 h-3 w-3" />
                        Submit for Review
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                        disabled={deletingDraftId === draft.id}
                        onClick={() => handleDeleteDraft(draft.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {pendingCount > 0 && (
          <div className="flex items-start gap-3 rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-4 py-3">
            <Clock className="h-4 w-4 mt-0.5 text-yellow-600 dark:text-yellow-400 shrink-0" />
            <p className="text-sm text-yellow-700 dark:text-yellow-300">
              You have {pendingCount} agent{pendingCount > 1 ? "s" : ""} pending review.
              An admin must approve {pendingCount > 1 ? "them" : "it"} before {pendingCount > 1 ? "they become" : "it becomes"} visible to other users.
            </p>
          </div>
        )}

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
                supported_ides={agent.supported_ides as string[] | undefined}
                inferred_supported_ides={agent.inferred_supported_ides as string[] | undefined}
                className={`animate-in stagger-${Math.min(i + 1, 5)}`}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
