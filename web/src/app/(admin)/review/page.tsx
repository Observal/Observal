"use client";

import { useState, useCallback, useMemo } from "react";
import { CheckCircle2, X, Trash2, LayoutGrid, TableProperties, Eye } from "lucide-react";
import { useReviewAgents, useReviewComponents, useReviewAction, useReviewDelete } from "@/hooks/use-api";
import { useAuthGuard } from "@/hooks/use-auth";
import type { ReviewItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { PageHeader } from "@/components/layouts/page-header";
import { CardSkeleton, TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { ValidationBadge, ValidationDetails, ComponentReadinessBadge } from "@/components/review/validation-badges";
import { ReviewDetailSheet } from "@/components/review/review-detail-sheet";
import { ReviewDiffSheet } from "@/components/review/review-diff-sheet";

type ViewMode = "list" | "grid";

function ReviewCard({ item, onDelete, onItemClick, isAdmin }: {
  item: ReviewItem;
  onDelete: (id: string, type?: string) => void;
  onItemClick: (item: ReviewItem) => void;
  isAdmin?: boolean;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div className="rounded-md border border-border bg-card p-4 space-y-3 hover:bg-muted/20 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <button onClick={() => onItemClick(item)} className="hover:underline text-left">
            <h4 className="text-sm font-[family-name:var(--font-display)] font-semibold truncate">
              {item.name ?? "Unnamed"}
            </h4>
          </button>
          {item.submitted_by && (
            <p className="text-xs text-muted-foreground mt-0.5">
              by {item.submitted_by}
            </p>
          )}
        </div>
        {item.type && (
          <Badge variant="outline" className="text-[10px] shrink-0">
            {item.type}
          </Badge>
        )}
      </div>

      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>
          {item.submitted_at || item.created_at
            ? new Date((item.submitted_at ?? item.created_at)!).toLocaleDateString()
            : ""}
        </span>
        <ValidationBadge item={item} />
      </div>

      <ValidationDetails results={item.validation_results} />
      <ComponentReadinessBadge item={item} />

      {confirmDelete && (
        <div className="flex items-center gap-2 p-2 rounded bg-destructive/5 border border-destructive/15 animate-in">
          <p className="text-xs text-destructive flex-1">Permanently delete this submission?</p>
          <Button
            size="sm"
            className="h-7 text-xs bg-destructive hover:bg-destructive/90 text-destructive-foreground shadow-none"
            onClick={() => { onDelete(item.id, item.type); setConfirmDelete(false); }}
          >
            Delete
          </Button>
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => setConfirmDelete(false)}>
            <X className="h-3 w-3" />
          </Button>
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          className="h-7 text-xs flex-1 bg-info/10 hover:bg-info/20 text-info border border-info/25 shadow-none"
          onClick={() => onItemClick(item)}
        >
          <Eye className="h-3 w-3 mr-1.5" />
          Review
        </Button>
        {isAdmin && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                  onClick={() => setConfirmDelete(true)}
                  aria-label="Delete submission"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Permanently delete (admin only)</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>
    </div>
  );
}

function ReviewRow({ item, onDelete, onItemClick, isAdmin }: {
  item: ReviewItem;
  onDelete: (id: string, type?: string) => void;
  onItemClick: (item: ReviewItem) => void;
  isAdmin?: boolean;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div className="px-5 py-4 border-b border-border last:border-b-0 hover:bg-muted/20 transition-colors space-y-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2.5">
            <button
              onClick={() => onItemClick(item)}
              className="text-sm font-[family-name:var(--font-display)] font-semibold truncate hover:underline text-left"
            >
              {item.name ?? "Unnamed"}
            </button>
            {item.type && (
              <Badge variant="outline" className="text-[10px] shrink-0">
                {item.type}
              </Badge>
            )}
            {item.version && (
              <span className="text-xs text-muted-foreground">v{item.version}</span>
            )}
            <ValidationBadge item={item} />
          </div>
          {item.description && (
            <p className="text-xs text-muted-foreground line-clamp-2 max-w-2xl">
              {item.description}
            </p>
          )}
          <ValidationDetails results={item.validation_results} />
          <ComponentReadinessBadge item={item} />
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {item.submitted_by && <span>by {item.submitted_by}</span>}
            {(item.submitted_at || item.created_at) && (
              <span>{new Date((item.submitted_at ?? item.created_at)!).toLocaleDateString()}</span>
            )}
            {item.owner && <span>{item.owner}</span>}
          </div>
        </div>
        {confirmDelete ? (
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-xs text-destructive">Permanently delete?</span>
            <Button
              size="sm"
              className="h-8 text-xs bg-destructive hover:bg-destructive/90 text-destructive-foreground shadow-none"
              onClick={() => { onDelete(item.id, item.type); setConfirmDelete(false); }}
            >
              Delete
            </Button>
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => setConfirmDelete(false)}>
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2 shrink-0">
            <Button
              size="sm"
              className="h-8 text-xs bg-info/10 hover:bg-info/20 text-info border border-info/25 shadow-none"
              onClick={() => onItemClick(item)}
            >
              <Eye className="h-3.5 w-3.5 mr-1.5" />
              Review
            </Button>
            {isAdmin && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                      onClick={() => setConfirmDelete(true)}
                      aria-label="Delete submission"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Permanently delete (admin only)</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function AgentItemList({
  items,
  view,
  onDelete,
  onItemClick,
  isAdmin,
}: {
  items: ReviewItem[];
  view: ViewMode;
  onDelete: (id: string, type?: string) => void;
  onItemClick: (item: ReviewItem) => void;
  isAdmin?: boolean;
}) {
  const grouped = useMemo(() => {
    const bundles = new Map<string, { name: string; items: ReviewItem[] }>();
    const ungrouped: ReviewItem[] = [];
    for (const item of items) {
      if (item.bundle_id && item.bundle_name) {
        const existing = bundles.get(item.bundle_id);
        if (existing) {
          existing.items.push(item);
        } else {
          bundles.set(item.bundle_id, { name: item.bundle_name, items: [item] });
        }
      } else {
        ungrouped.push(item);
      }
    }
    return { bundles: Array.from(bundles.values()), ungrouped };
  }, [items]);

  const renderItems = (list: ReviewItem[]) =>
    view === "list" ? (
      <div className="animate-in rounded-md border border-border overflow-hidden">
        {list.map((item) => (
          <ReviewRow
            key={item.id}
            item={item}
            onDelete={onDelete}
            onItemClick={onItemClick}
            isAdmin={isAdmin}
          />
        ))}
      </div>
    ) : (
      <div className="animate-in grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {list.map((item) => (
          <ReviewCard
            key={item.id}
            item={item}
            onDelete={onDelete}
            onItemClick={onItemClick}
            isAdmin={isAdmin}
          />
        ))}
      </div>
    );

  if (grouped.bundles.length === 0) return renderItems(items);

  return (
    <div className="space-y-6">
      {grouped.bundles.map((bundle) => (
        <div key={bundle.name} className="space-y-3">
          <h3 className="text-sm font-[family-name:var(--font-display)] font-semibold text-muted-foreground border-b border-border pb-2">
            Bundle: {bundle.name}
          </h3>
          {renderItems(bundle.items)}
        </div>
      ))}
      {grouped.ungrouped.length > 0 && (
        <div className="space-y-3">
          {grouped.bundles.length > 0 && (
            <h3 className="text-sm font-[family-name:var(--font-display)] font-semibold text-muted-foreground border-b border-border pb-2">
              Standalone Agents
            </h3>
          )}
          {renderItems(grouped.ungrouped)}
        </div>
      )}
    </div>
  );
}

function ReviewItemList({
  items,
  view,
  onDelete,
  onItemClick,
  isAdmin,
}: {
  items: ReviewItem[];
  view: ViewMode;
  onDelete: (id: string, type?: string) => void;
  onItemClick: (item: ReviewItem) => void;
  isAdmin?: boolean;
}) {
  return view === "list" ? (
    <div className="animate-in rounded-md border border-border overflow-hidden">
      {items.map((item) => (
        <ReviewRow
          key={item.id}
          item={item}
          onDelete={onDelete}
          onItemClick={onItemClick}
          isAdmin={isAdmin}
        />
      ))}
    </div>
  ) : (
    <div className="animate-in grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {items.map((item) => (
        <ReviewCard
          key={item.id}
          item={item}
          onDelete={onDelete}
          onItemClick={onItemClick}
          isAdmin={isAdmin}
        />
      ))}
    </div>
  );
}

export default function ReviewPage() {
  const { role } = useAuthGuard();
  const isAdmin = role === "admin" || role === "super_admin";
  const { data: agents, isLoading: agentsLoading, isError: agentsError, error: agentsErr, refetch: refetchAgents } = useReviewAgents();
  const { data: components, isLoading: componentsLoading, isError: componentsError, error: componentsErr, refetch: refetchComponents } = useReviewComponents();
  const reviewAction = useReviewAction();
  const reviewDelete = useReviewDelete();
  const [view, setView] = useState<ViewMode>("grid");
  const [activeTab, setActiveTab] = useState("agents");
  const [selectedItem, setSelectedItem] = useState<ReviewItem | null>(null);
  const [diffItem, setDiffItem] = useState<ReviewItem | null>(null);

  const agentCount = (agents ?? []).length;
  const componentCount = (components ?? []).length;
  const totalPending = agentCount + componentCount;

  const handleApprove = useCallback(
    (id: string, type?: string) => reviewAction.mutate({ id, type, action: "approve" }),
    [reviewAction],
  );

  const handleReject = useCallback(
    (id: string, reason: string, type?: string) => reviewAction.mutate({ id, type, action: "reject", reason }),
    [reviewAction],
  );

  const handleDelete = useCallback(
    (id: string, type?: string) => reviewDelete.mutate({ id, type }),
    [reviewDelete],
  );

  const handleItemClick = useCallback(
    (item: ReviewItem) => {
      if (item.type === "agent") {
        setDiffItem(item);
      } else {
        setSelectedItem(item);
      }
    },
    [],
  );

  return (
    <>
      <PageHeader
        title="Review Queue"
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Review" },
        ]}
        actionButtonsRight={
          <div className="flex items-center gap-2">
            {!agentsLoading && !componentsLoading && totalPending > 0 && (
              <Badge variant="secondary" className="text-xs">
                {totalPending} pending
              </Badge>
            )}
            <div className="flex items-center border border-border rounded-md overflow-hidden">
              <Button
                variant={view === "list" ? "secondary" : "ghost"}
                size="sm"
                className="rounded-none h-8 px-2.5"
                onClick={() => setView("list")}
                aria-label="List view"
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
        }
      />
      <div className="p-6 w-full mx-auto space-y-4">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="agents">
              Agents{!agentsLoading ? ` (${agentCount})` : ""}
            </TabsTrigger>
            <TabsTrigger value="components">
              Components{!componentsLoading ? ` (${componentCount})` : ""}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="agents">
            {agentsLoading ? (
              view === "list" ? (
                <TableSkeleton rows={6} cols={4} />
              ) : (
                <CardSkeleton count={3} columns={3} />
              )
            ) : agentsError ? (
              <ErrorState message={agentsErr?.message} onRetry={() => refetchAgents()} />
            ) : agentCount === 0 ? (
              <EmptyState
                icon={CheckCircle2}
                title="No agents to review"
                description="All agent submissions have been reviewed. New items will appear here when agents are submitted."
              />
            ) : (
              <AgentItemList
                items={agents!}
                view={view}
                onDelete={handleDelete}
                onItemClick={handleItemClick}
                isAdmin={isAdmin}
              />
            )}
          </TabsContent>

          <TabsContent value="components">
            {componentsLoading ? (
              view === "list" ? (
                <TableSkeleton rows={6} cols={4} />
              ) : (
                <CardSkeleton count={3} columns={3} />
              )
            ) : componentsError ? (
              <ErrorState message={componentsErr?.message} onRetry={() => refetchComponents()} />
            ) : componentCount === 0 ? (
              <EmptyState
                icon={CheckCircle2}
                title="No components to review"
                description="All component submissions have been reviewed. New items will appear here when components are submitted."
              />
            ) : (
              <ReviewItemList
                items={components!}
                view={view}
                onDelete={handleDelete}
                onItemClick={handleItemClick}
                isAdmin={isAdmin}
              />
            )}
          </TabsContent>
        </Tabs>
      </div>

      <ReviewDetailSheet
        item={selectedItem}
        open={!!selectedItem}
        onOpenChange={(open) => { if (!open) setSelectedItem(null); }}
        onApprove={handleApprove}
        onReject={handleReject}
        onDelete={handleDelete}
      />

      <ReviewDiffSheet
        item={diffItem}
        open={!!diffItem}
        onOpenChange={(open) => { if (!open) setDiffItem(null); }}
        onApprove={handleApprove}
        onReject={handleReject}
      />
    </>
  );
}
