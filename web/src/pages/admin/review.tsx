// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: Apache-2.0


import { useState, useCallback, useEffect, useMemo } from "react";
import { Building2, CheckCircle2, LayoutGrid, TableProperties, Eye } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearch } from "@tanstack/react-router";
import {
  useDecideTeamVisibility,
  useReviewAgents,
  useReviewComponents,
  useReviewAction,
  useReviewSubscription,
  useTeamVisibilityRequests,
} from "@/hooks/use-api";
import { useAuthGuard } from "@/hooks/use-auth";
import type { ReviewItem, TeamVisibilityRequest } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/layouts/page-header";
import { CardSkeleton, TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { ValidationBadge, ValidationDetails, ComponentReadinessBadge } from "@/components/review/validation-badges";
import { ReviewDetailSheet } from "@/components/review/review-detail-sheet";
import { ReviewDiffSheet } from "@/components/review/review-diff-sheet";

type ViewMode = "list" | "grid";

function ReviewCard({ item, onItemClick }: {
  item: ReviewItem;
  onItemClick: (item: ReviewItem) => void;
}) {

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

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          className="h-7 text-xs flex-1 bg-info/10 hover:bg-info/20 text-info border border-info/25 shadow-none"
          onClick={() => onItemClick(item)}
        >
          <Eye className="h-3 w-3 mr-1.5" />
          Review
        </Button>
      </div>
    </div>
  );
}

function ReviewRow({ item, onItemClick }: {
  item: ReviewItem;
  onItemClick: (item: ReviewItem) => void;
}) {
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
        <div className="flex items-center gap-2 shrink-0">
          <Button
            size="sm"
            className="h-8 text-xs bg-info/10 hover:bg-info/20 text-info border border-info/25 shadow-none"
            onClick={() => onItemClick(item)}
          >
            <Eye className="h-3.5 w-3.5 mr-1.5" />
            Review
          </Button>
        </div>
      </div>
    </div>
  );
}

function AgentItemList({
  items,
  view,
  onItemClick,
}: {
  items: ReviewItem[];
  view: ViewMode;
  onItemClick: (item: ReviewItem) => void;
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
            onItemClick={onItemClick}
          />
        ))}
      </div>
    ) : (
      <div className="animate-in grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {list.map((item) => (
          <ReviewCard
            key={item.id}
            item={item}
            onItemClick={onItemClick}
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
  onItemClick,
}: {
  items: ReviewItem[];
  view: ViewMode;
  onItemClick: (item: ReviewItem) => void;
}) {
  return view === "list" ? (
    <div className="animate-in rounded-md border border-border overflow-hidden">
      {items.map((item) => (
        <ReviewRow
          key={item.id}
          item={item}
          onItemClick={onItemClick}
        />
      ))}
    </div>
  ) : (
    <div className="animate-in grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {items.map((item) => (
        <ReviewCard
          key={item.id}
          item={item}
          onItemClick={onItemClick}
        />
      ))}
    </div>
  );
}

export default function ReviewPage() {
  useAuthGuard();
  useReviewSubscription();
  const { data: agents, isLoading: agentsLoading, isError: agentsError, error: agentsErr, refetch: refetchAgents } = useReviewAgents();
  const { data: components, isLoading: componentsLoading, isError: componentsError, error: componentsErr, refetch: refetchComponents } = useReviewComponents();
  const { data: teamspaces, isLoading: teamspacesLoading, isError: teamspacesError, error: teamspacesErr, refetch: refetchTeamspaces } = useTeamVisibilityRequests();
  const reviewAction = useReviewAction();
  const teamspaceAction = useDecideTeamVisibility();
  const [view, setView] = useState<ViewMode>("grid");
  // ?tab= lets an inbox item open the tab that actually holds the submission it
  // names. Absent, the queue opens on agents as before.
  const { tab: tabFromUrl } = useSearch({ from: "/_authed/_admin/review" });
  const [activeTab, setActiveTab] = useState<string>(tabFromUrl ?? "agents");
  // useState only reads the initial value, so a ?tab= change while this page
  // is already mounted (an inbox link clicked from the sidebar) must be
  // applied explicitly or the link silently does nothing.
  useEffect(() => {
    if (tabFromUrl) setActiveTab(tabFromUrl);
  }, [tabFromUrl]);
  const [selectedItem, setSelectedItem] = useState<ReviewItem | null>(null);
  const [diffItem, setDiffItem] = useState<ReviewItem | null>(null);
  const [nestedDiffItem, setNestedDiffItem] = useState<ReviewItem | null>(null);
  const [rejectTeamspace, setRejectTeamspace] = useState<TeamVisibilityRequest | null>(null);
  const [teamspaceReason, setTeamspaceReason] = useState("");

  const agentCount = (agents ?? []).length;
  const componentCount = (components ?? []).length;
  const teamspaceCount = (teamspaces ?? []).length;
  const totalPending = agentCount + componentCount + teamspaceCount;

  const handleApprove = useCallback(
    (id: string, type?: string, category?: string) => reviewAction.mutate({ id, type, action: "approve", category }),
    [reviewAction],
  );

  const handleReject = useCallback(
    (id: string, reason: string, type?: string) => reviewAction.mutate({ id, type, action: "reject", reason }),
    [reviewAction],
  );

  const queryClient = useQueryClient();

  const handleItemClick = useCallback(
    (item: ReviewItem) => {
      setDiffItem(item);
    },
    [],
  );

  const handleOpenComponentReview = useCallback(
    async (id: string, type: string) => {
      const singularType = type.replace(/s$/, "");
      let list = components ?? [];
      // If not found yet, refetch first (component may have just been submitted)
      if (!list.find((c) => c.id === id)) {
        const result = await refetchComponents();
        list = result.data ?? list;
      }
      const found = list.find((c) => c.id === id || (c.type === singularType && c.id === id));
      if (found) setNestedDiffItem(found);
    },
    [components, refetchComponents],
  );

  const handleApproveWithRefetch = useCallback(
    (id: string, type?: string) => {
      reviewAction.mutate({ id, type, action: "approve" }, {
        onSuccess: async () => {
          setNestedDiffItem(null);
          const [freshAgents] = await Promise.all([refetchAgents(), refetchComponents()]);
          // Update diffItem in-place with fresh blocking_components so the sheet reflects the change
          setDiffItem((prev) => {
            if (!prev) return prev;
            const updated = (freshAgents.data ?? []).find((a) => a.id === prev.id);
            return updated ?? prev;
          });
        },
      });
    },
    [reviewAction, refetchAgents, refetchComponents],
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
            {!agentsLoading && !componentsLoading && !teamspacesLoading && totalPending > 0 && (
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
      <div className="page-body w-full mx-auto space-y-4">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="agents">
              Agents{!agentsLoading ? ` (${agentCount})` : ""}
            </TabsTrigger>
            <TabsTrigger value="components">
              Components{!componentsLoading ? ` (${componentCount})` : ""}
            </TabsTrigger>
            <TabsTrigger value="teamspaces">
              Teamspaces{!teamspacesLoading ? ` (${teamspaceCount})` : ""}
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
                onItemClick={handleItemClick}
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
                onItemClick={handleItemClick}
              />
            )}
          </TabsContent>

          <TabsContent value="teamspaces">
            {teamspacesLoading ? (
              <CardSkeleton count={3} columns={3} />
            ) : teamspacesError ? (
              <ErrorState message={teamspacesErr?.message} onRetry={() => refetchTeamspaces()} />
            ) : teamspaceCount === 0 ? (
              <EmptyState
                icon={CheckCircle2}
                title="No teamspaces to review"
                description="Public visibility requests will appear here."
              />
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {(teamspaces ?? []).map((team: TeamVisibilityRequest) => (
                  <div
                    key={team.team_id}
                    data-testid={`teamspace-review-${team.team_id}`}
                    className="space-y-3 rounded-md border border-border bg-card p-4"
                  >
                    <div className="flex items-start gap-3">
                      <Building2 className="mt-0.5 h-4 w-4 text-primary-accent" />
                      <div className="min-w-0">
                        <h3 className="truncate text-sm font-semibold">{team.name}</h3>
                        <p className="font-mono text-xs text-muted-foreground">{team.handle}</p>
                      </div>
                    </div>
                    {team.description && <p className="line-clamp-2 text-xs text-muted-foreground">{team.description}</p>}
                    <p className="text-xs text-muted-foreground">
                      Requested by {team.requested_by_username ? `@${team.requested_by_username}` : "a user"}
                    </p>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        className="flex-1"
                        disabled={teamspaceAction.isPending}
                        onClick={() => teamspaceAction.mutate({ id: team.team_id, approve: true })}
                      >
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="flex-1"
                        disabled={teamspaceAction.isPending}
                        onClick={() => setRejectTeamspace(team)}
                      >
                        Reject
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>

      <Dialog
        open={!!rejectTeamspace}
        onOpenChange={(open) => {
          if (!open) {
            setRejectTeamspace(null);
            setTeamspaceReason("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject public visibility</DialogTitle>
            <DialogDescription>
              The teamspace stays private, and its owner can submit another request after making changes.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="teamspace-rejection-reason">Reason (optional)</Label>
            <Textarea
              id="teamspace-rejection-reason"
              value={teamspaceReason}
              maxLength={500}
              onChange={(event) => setTeamspaceReason(event.target.value)}
              placeholder="Explain what needs to change before this teamspace can become public."
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectTeamspace(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={teamspaceAction.isPending}
              onClick={() => {
                if (!rejectTeamspace) return;
                teamspaceAction.mutate(
                  { id: rejectTeamspace.team_id, approve: false, reason: teamspaceReason.trim() || undefined },
                  {
                    onSuccess: () => {
                      setRejectTeamspace(null);
                      setTeamspaceReason("");
                    },
                  },
                );
              }}
            >
              Reject request
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ReviewDetailSheet
        item={selectedItem}
        open={!!selectedItem}
        onOpenChange={(open) => { if (!open) setSelectedItem(null); }}
        onApprove={handleApprove}
        onReject={handleReject}
      />

      <ReviewDiffSheet
        item={diffItem}
        open={!!diffItem}
        onOpenChange={(open) => { if (!open) setDiffItem(null); }}
        onApprove={handleApprove}
        onReject={handleReject}
        onOpenComponentReview={handleOpenComponentReview}
      />
      <ReviewDiffSheet
        item={nestedDiffItem}
        open={!!nestedDiffItem}
        onOpenChange={(open) => { if (!open) setNestedDiffItem(null); }}
        onApprove={handleApproveWithRefetch}
        onReject={handleReject}
      />
    </>
  );
}
