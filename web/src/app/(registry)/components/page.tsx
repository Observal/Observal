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
  Plus,
  Send,
  Trash2,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  useRegistryList,
  useMyComponents,
  useComponentSubmit,
  useComponentSaveDraft,
  useComponentSubmitDraft,
  useComponentDelete,
} from "@/hooks/use-api";
import { useAuthGuard } from "@/hooks/use-auth";
import type { RegistryType } from "@/lib/api";
import type { RegistryItem } from "@/lib/types";
import { SubmitComponentDialog } from "@/components/registry/submit-component-dialog";
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

const TYPE_PLURAL_LABELS: Record<string, string> = Object.fromEntries(
  TYPES.map((t) => [t.value, t.label]),
);

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
  const { ready: authReady, role } = useAuthGuard();
  const [activeType, setActiveType] = useState<RegistryType>("mcps");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [view, setView] = useState<ViewMode>("table");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [submitOpen, setSubmitOpen] = useState(false);
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

  const { data: myItems } = useMyComponents(activeType);
  const myDrafts = useMemo(
    () => (myItems ?? []).filter((i) => i.status === "draft" || i.status === "pending" || i.status === "rejected"),
    [myItems],
  );

  const submitMutation = useComponentSubmit(activeType);
  const saveDraftMutation = useComponentSaveDraft(activeType);
  const submitDraftMutation = useComponentSubmitDraft(activeType);
  const deleteMutation = useComponentDelete(activeType);

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

      <div className="p-6 lg:p-8 w-full mx-auto space-y-5">
        {/* Toolbar */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative max-w-sm flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder={`Search ${TYPE_PLURAL_LABELS[activeType] ?? activeType}...`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9"
            />
          </div>
          {authReady && role && (
            <Button size="sm" className="h-9" onClick={() => setSubmitOpen(true)}>
              <Plus className="h-4 w-4 mr-1.5" />
              Create
            </Button>
          )}
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
            title={`No ${TYPE_PLURAL_LABELS[activeType] ?? activeType} found`}
            description={
              debouncedSearch
                ? `No ${TYPE_PLURAL_LABELS[activeType] ?? activeType} match "${debouncedSearch}". Try a different search.`
                : `No ${TYPE_PLURAL_LABELS[activeType] ?? activeType} have been registered yet.`
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

        {/* My Drafts / Submissions */}
        {authReady && role && myDrafts.length > 0 && (
          <div className="space-y-3 pt-4 border-t border-border">
            <h3 className="text-sm font-medium text-muted-foreground">
              My Submissions
            </h3>
            <div className="space-y-2">
              {myDrafts.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center justify-between rounded-lg border border-border px-4 py-3"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <StatusBadge status={item.status ?? "draft"} />
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">
                        {item.name}
                      </p>
                      {item.description && (
                        <p className="text-xs text-muted-foreground truncate max-w-xs">
                          {item.description}
                        </p>
                      )}
                      {item.status === "rejected" && item.rejection_reason && (
                        <p className="text-xs text-destructive mt-0.5 line-clamp-2" title={item.rejection_reason}>
                          Rejected: {item.rejection_reason}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {item.status === "draft" && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => submitDraftMutation.mutate(item.id)}
                        disabled={submitDraftMutation.isPending}
                      >
                        <Send className="h-3 w-3 mr-1" />
                        Submit
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                      onClick={() => deleteMutation.mutate(item.id)}
                      disabled={deleteMutation.isPending}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <SubmitComponentDialog
        open={submitOpen}
        onOpenChange={setSubmitOpen}
        type={activeType}
        onSubmit={(body) => {
          submitMutation.mutate(body, {
            onSuccess: () => setSubmitOpen(false),
          });
        }}
        onSaveDraft={(body) => {
          saveDraftMutation.mutate(body, {
            onSuccess: () => setSubmitOpen(false),
          });
        }}
        isSubmitting={submitMutation.isPending}
        isSavingDraft={saveDraftMutation.isPending}
      />
    </>
  );
}
