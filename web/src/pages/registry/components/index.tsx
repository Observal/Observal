// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: Apache-2.0


import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { useState, useEffect, useRef, useMemo, useCallback } from "react";
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
  FileEdit,
  X,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PickerSelect } from "@/components/ui/picker-select";
import { UserSearchInput } from "@/components/shared/user-search-input";
import {
  useRegistryList,
  useMyComponents,
  useComponentSubmit,
  useComponentSaveDraft,
  useComponentSubmitDraft,
  useComponentUpdateDraft,
  useStartEdit,
  useCancelEdit,
} from "@/hooks/use-api";
import { useAuthGuard } from "@/hooks/use-auth";
import type { RegistryType } from "@/lib/api";
import type { RegistryItem } from "@/lib/types";
import {
  HOOK_EVENTS,
  HOOK_SCOPES,
  MCP_CATEGORIES,
  PROMPT_CATEGORIES,
  SANDBOX_RUNTIME_TYPES,
  SKILL_TASK_TYPES,
  SubmitComponentDialog,
} from "@/components/registry/submit-component-dialog";
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
type FilterKey = "category" | "task_type" | "event" | "scope" | "runtime_type";

type TypeFilter = {
  key: FilterKey;
  label: string;
  options: string[];
};

const TYPE_FILTERS: Partial<Record<RegistryType, TypeFilter[]>> = {
  mcps: [{ key: "category", label: "Category", options: MCP_CATEGORIES }],
  skills: [{ key: "task_type", label: "Task type", options: SKILL_TASK_TYPES }],
  hooks: [
    { key: "event", label: "Event", options: HOOK_EVENTS },
    { key: "scope", label: "Scope", options: HOOK_SCOPES },
  ],
  prompts: [{ key: "category", label: "Category", options: PROMPT_CATEGORIES }],
  sandboxes: [{ key: "runtime_type", label: "Runtime", options: SANDBOX_RUNTIME_TYPES }],
};

function formatOption(value: string): string {
  return value.replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

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
            to="/components/$componentId" params={{ componentId: row.original.id }} search={{ type: activeType }}
            className="font-medium text-sm hover:underline underline-offset-4"
          >
            {row.original.qualified_name ?? row.original.name}
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
  const searchParams = useSearch({ from: "/_authed/components/" });
  const { ready: authReady, role } = useAuthGuard();
  const activeType = searchParams.type ?? "mcps";
  const [search, setSearch] = useState(searchParams.search ?? "");
  const [debouncedSearch, setDebouncedSearch] = useState(searchParams.search ?? "");
  const [publisherQuery, setPublisherQuery] = useState(searchParams.namespace ? `@${searchParams.namespace}` : "");
  const [view, setView] = useState<ViewMode>("table");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [submitOpen, setSubmitOpen] = useState(false);
  const [editItem, setEditItem] = useState<RegistryItem | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    timerRef.current = setTimeout(() => {
      setDebouncedSearch(search);
    }, 300);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [search]);

  useEffect(() => {
    setPublisherQuery(searchParams.namespace ? `@${searchParams.namespace}` : "");
  }, [searchParams.namespace]);

  const typeFilters = TYPE_FILTERS[activeType] ?? [];
  const registryFilters: Record<string, string> = {
    ...(debouncedSearch ? { search: debouncedSearch } : {}),
    ...(searchParams.namespace ? { namespace: searchParams.namespace } : {}),
  };
  for (const filter of typeFilters) {
    const value = searchParams[filter.key];
    if (value) registryFilters[filter.key] = value;
  }

  const { data, isLoading, isError, error, refetch } = useRegistryList(activeType, registryFilters);

  const { data: myItems } = useMyComponents(activeType);
  const myDrafts = useMemo(
    () => (myItems ?? []).filter((i) => ["draft", "pending", "rejected", "archived"].includes(i.status ?? "")),
    [myItems],
  );

  const submitMutation = useComponentSubmit(activeType);
  const saveDraftMutation = useComponentSaveDraft(activeType);
  const submitDraftMutation = useComponentSubmitDraft(activeType);
  const updateDraftMutation = useComponentUpdateDraft(activeType);
  const startEditMutation = useStartEdit(activeType);
  const cancelEditMutation = useCancelEdit(activeType);

  const editItemRef = useRef(editItem);
  editItemRef.current = editItem;
  const activeTypeRef = useRef(activeType);
  activeTypeRef.current = activeType;

  useEffect(() => {
    const handleBeforeUnload = () => {
      const item = editItemRef.current;
      if (item?.status === "pending") {
        const type = activeTypeRef.current;
        const token = sessionStorage.getItem("observal_access_token");
        fetch(`/api/v1/${type}/${item.id}/cancel-edit`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          keepalive: true,
        });
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, []);

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
      router.navigate({ to: "/components/$componentId", params: { componentId: id }, search: { type: activeType } });
    },
    [router, activeType],
  );

  function updateFilters(next: Partial<typeof searchParams>) {
    router.navigate({
      to: "/components",
      search: { ...searchParams, ...next },
      replace: true,
    });
  }

  function clearFilters() {
    setSearch("");
    setDebouncedSearch("");
    setPublisherQuery("");
    updateFilters({
      search: undefined,
      namespace: undefined,
      category: undefined,
      task_type: undefined,
      event: undefined,
      scope: undefined,
      runtime_type: undefined,
    });
  }

  const hasFilters = !!(
    search ||
    searchParams.namespace ||
    typeFilters.some((filter) => searchParams[filter.key])
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
        <div className="space-y-2">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative max-w-md flex-1 min-w-[240px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                aria-label={`Search ${TYPE_PLURAL_LABELS[activeType] ?? activeType}`}
                placeholder="Search name, slug, or description..."
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  updateFilters({ search: event.target.value || undefined });
                }}
                className="pl-9 h-9"
              />
            </div>
            <UserSearchInput
              value={publisherQuery}
              onValueChange={(value) => {
                setPublisherQuery(value);
                if (searchParams.namespace && value !== searchParams.namespace && value !== `@${searchParams.namespace}`) {
                  updateFilters({ namespace: undefined });
                }
              }}
              onSelect={(user) => {
                if (!user.username) return;
                setPublisherQuery(`@${user.username}`);
                updateFilters({ namespace: user.username });
              }}
              placeholder="Publisher"
              className="h-9 w-[220px]"
            />
            {typeFilters.map((filter) => (
              <PickerSelect
                key={filter.key}
                value={searchParams[filter.key] ?? ""}
                onValueChange={(value) => updateFilters({ [filter.key]: value || undefined })}
                options={[
                  { value: "", label: `Any ${filter.label.toLowerCase()}` },
                  ...filter.options.map((option) => ({ value: option, label: formatOption(option) })),
                ]}
                placeholder={filter.label}
                className="w-[180px]"
                inputClassName="h-9"
              />
            ))}
            {authReady && role && (
              <Button size="sm" className="h-9" onClick={() => { setEditItem(null); setSubmitOpen(true); }}>
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
          {hasFilters && (
            <div className="flex min-h-7 items-center gap-2 flex-wrap" aria-label="Active filters">
              {searchParams.namespace && (
                <Button variant="secondary" size="sm" className="h-7 gap-1 px-2 text-xs" onClick={() => updateFilters({ namespace: undefined })}>
                  Publisher: @{searchParams.namespace}
                  <X className="h-3 w-3" />
                </Button>
              )}
              {typeFilters.map((filter) => {
                const value = searchParams[filter.key];
                if (!value) return null;
                return (
                  <Button key={filter.key} variant="secondary" size="sm" className="h-7 gap-1 px-2 text-xs" onClick={() => updateFilters({ [filter.key]: undefined })}>
                    {filter.label}: {formatOption(value)}
                    <X className="h-3 w-3" />
                  </Button>
                );
              })}
              <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-muted-foreground" onClick={clearFilters}>
                Clear all
              </Button>
            </div>
          )}
        </div>

        {/* Type filter tabs */}
        <div className="flex items-center gap-1 border-b border-border">
          {TYPES.map((t) => (
            <button
              key={t.value}
              onClick={() => {
                updateFilters({
                  type: t.value,
                  category: undefined,
                  task_type: undefined,
                  event: undefined,
                  scope: undefined,
                  runtime_type: undefined,
                });
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
              hasFilters
                ? `No ${TYPE_PLURAL_LABELS[activeType] ?? activeType} match the active search and filters.`
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
                        {item.qualified_name ?? item.name}
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
                    {(item.status === "draft" || item.status === "rejected" || item.status === "pending") && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        disabled={startEditMutation.isPending}
                        onClick={() => {
                          if (item.status === "pending") {
                            startEditMutation.mutate(item.id, {
                              onSuccess: () => { setEditItem(item); setSubmitOpen(true); },
                            });
                          } else {
                            setEditItem(item); setSubmitOpen(true);
                          }
                        }}
                      >
                        <FileEdit className="h-3 w-3 mr-1" />
                        Edit
                      </Button>
                    )}
                    {(item.status === "draft" || item.status === "rejected") && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => submitDraftMutation.mutate(item.id)}
                        disabled={submitDraftMutation.isPending}
                      >
                        <Send className="h-3 w-3 mr-1" />
                        {item.status === "rejected" ? "Resubmit" : "Submit"}
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <SubmitComponentDialog
        key={editItem?.id ?? "new"}
        open={submitOpen}
        onOpenChange={(v) => {
          if (!v && editItem?.status === "pending") {
            cancelEditMutation.mutate(editItem.id);
          }
          setSubmitOpen(v);
          if (!v) setEditItem(null);
        }}
        type={activeType}
        editItem={editItem as Record<string, unknown> | null}
        onSubmit={(body) => {
          if (editItem) {
            if (editItem.status === "pending") {
              updateDraftMutation.mutate({ id: editItem.id, body }, {
                onSuccess: () => { setSubmitOpen(false); setEditItem(null); },
              });
            } else {
              submitDraftMutation.mutate(editItem.id, {
                onSuccess: () => { setSubmitOpen(false); setEditItem(null); },
              });
            }
          } else {
            submitMutation.mutate(body, {
              onSuccess: () => setSubmitOpen(false),
            });
          }
        }}
        onSaveDraft={(body) => {
          saveDraftMutation.mutate(body, {
            onSuccess: () => setSubmitOpen(false),
          });
        }}
        onUpdateDraft={(id, body) => {
          updateDraftMutation.mutate({ id, body }, {
            onSuccess: () => { setSubmitOpen(false); setEditItem(null); },
          });
        }}
        isSubmitting={submitMutation.isPending || submitDraftMutation.isPending}
        isSavingDraft={saveDraftMutation.isPending || updateDraftMutation.isPending}
      />
    </>
  );
}
