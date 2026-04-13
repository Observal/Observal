"use client";

import { useState, useCallback } from "react";
import { CheckCircle2, X, LayoutGrid, TableProperties, AlertTriangle, ShieldCheck, ShieldX } from "lucide-react";
import { useReviewList, useReviewAction } from "@/hooks/use-api";
import type { ReviewItem, McpValidationResult } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/layouts/page-header";
import { CardSkeleton, TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

type ViewMode = "list" | "grid";

function ValidationBadge({ item }: { item: ReviewItem }) {
  if (item.type !== "mcp" || !item.validation_results?.length) return null;

  const failed = item.validation_results.filter((v: McpValidationResult) => !v.passed);
  const hasIssues = failed.some((v: McpValidationResult) => v.details?.includes("Issues:"));

  if (failed.length > 0) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-destructive bg-destructive/10 border border-destructive/25 rounded px-1.5 py-0.5">
        <ShieldX className="h-3 w-3" /> Validation failed
      </span>
    );
  }
  if (hasIssues) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-amber-500 bg-amber-500/10 border border-amber-500/25 rounded px-1.5 py-0.5">
        <AlertTriangle className="h-3 w-3" /> Has warnings
      </span>
    );
  }
  if (item.mcp_validated) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-success bg-success/10 border border-success/25 rounded px-1.5 py-0.5">
        <ShieldCheck className="h-3 w-3" /> Validated
      </span>
    );
  }
  return null;
}

function ValidationDetails({ results }: { results?: McpValidationResult[] }) {
  if (!results?.length) return null;

  const issues = results
    .filter((v: McpValidationResult) => v.details)
    .flatMap((v: McpValidationResult) => {
      const lines = v.details!.split("\n");
      return lines
        .filter((l: string) => l.startsWith("- "))
        .map((l: string) => l.slice(2));
    });

  if (!issues.length) return null;

  return (
    <div className="mt-2 p-2 rounded bg-amber-500/5 border border-amber-500/15 space-y-1">
      <p className="text-[10px] font-medium text-amber-500 flex items-center gap-1">
        <AlertTriangle className="h-3 w-3" /> Quality warnings ({issues.length})
      </p>
      {issues.map((issue: string, i: number) => (
        <p key={i} className="text-[10px] text-muted-foreground pl-4">
          {issue}
        </p>
      ))}
    </div>
  );
}

function ReviewCard({ item, onApprove, onReject }: {
  item: ReviewItem;
  onApprove: (id: string) => void;
  onReject: (id: string, reason: string) => void;
}) {
  const [showRejectInput, setShowRejectInput] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  const handleReject = useCallback(() => {
    if (!showRejectInput) {
      setShowRejectInput(true);
      return;
    }
    onReject(item.id, rejectReason);
    setShowRejectInput(false);
    setRejectReason("");
  }, [showRejectInput, rejectReason, item.id, onReject]);

  const cancelReject = useCallback(() => {
    setShowRejectInput(false);
    setRejectReason("");
  }, []);

  return (
    <div className="rounded-md border border-border bg-card p-4 space-y-3 hover:bg-muted/20 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-sm font-[family-name:var(--font-display)] font-semibold truncate">
            {item.name ?? "Unnamed"}
          </h4>
          {item.submitted_by && (
            <p className="text-xs text-muted-foreground mt-0.5">
              by {item.submitted_by}
            </p>
          )}
        </div>
        {item.type && (
          <Badge variant="outline" className="text-[10px] shrink-0">
            {item.type ?? item.listing_type ?? "-"}
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

      {/* Reject reason input */}
      {showRejectInput && (
        <div className="flex items-center gap-2 animate-in">
          <Input
            placeholder="Reason for rejection..."
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            className="h-7 text-xs flex-1"
            onKeyDown={(e) => {
              if (e.key === "Enter") handleReject();
              if (e.key === "Escape") cancelReject();
            }}
            autoFocus
          />
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={cancelReject}>
            <X className="h-3 w-3" />
          </Button>
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          className="h-7 text-xs flex-1 bg-success/10 hover:bg-success/20 text-success border border-success/25 shadow-none"
          onClick={() => onApprove(item.id)}
        >
          Approve
        </Button>
        <Button
          size="sm"
          className="h-7 text-xs flex-1 bg-destructive/10 hover:bg-destructive/20 text-destructive border border-destructive/25 shadow-none"
          onClick={handleReject}
        >
          {showRejectInput ? "Confirm" : "Reject"}
        </Button>
      </div>
    </div>
  );
}

function ReviewRow({ item, onApprove, onReject }: {
  item: ReviewItem;
  onApprove: (id: string) => void;
  onReject: (id: string, reason: string) => void;
}) {
  const [showRejectInput, setShowRejectInput] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  const handleReject = useCallback(() => {
    if (!showRejectInput) {
      setShowRejectInput(true);
      return;
    }
    onReject(item.id, rejectReason);
    setShowRejectInput(false);
    setRejectReason("");
  }, [showRejectInput, rejectReason, item.id, onReject]);

  const cancelReject = useCallback(() => {
    setShowRejectInput(false);
    setRejectReason("");
  }, []);

  return (
    <div className="px-5 py-4 border-b border-border last:border-b-0 hover:bg-muted/20 transition-colors space-y-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2.5">
            <span className="text-sm font-[family-name:var(--font-display)] font-semibold truncate">
              {item.name ?? "Unnamed"}
            </span>
            {item.type && (
              <Badge variant="outline" className="text-[10px] shrink-0">
                {item.type ?? item.listing_type ?? "-"}
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
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {item.submitted_by && <span>by {item.submitted_by}</span>}
            {(item.submitted_at || item.created_at) && (
              <span>{new Date((item.submitted_at ?? item.created_at)!).toLocaleDateString()}</span>
            )}
            {item.owner && <span>{item.owner}</span>}
          </div>
        </div>
        {showRejectInput ? (
          <div className="flex items-center gap-2 shrink-0">
            <Input
              placeholder="Reason for rejection..."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="h-8 text-xs w-52"
              onKeyDown={(e) => {
                if (e.key === "Enter") handleReject();
                if (e.key === "Escape") cancelReject();
              }}
              autoFocus
            />
            <Button
              size="sm"
              className="h-8 text-xs bg-destructive/10 hover:bg-destructive/20 text-destructive border border-destructive/25 shadow-none"
              onClick={handleReject}
            >
              Confirm
            </Button>
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={cancelReject}>
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2 shrink-0">
            <Button
              size="sm"
              className="h-8 text-xs bg-success/10 hover:bg-success/20 text-success border border-success/25 shadow-none"
              onClick={() => onApprove(item.id)}
            >
              Approve
            </Button>
            <Button
              size="sm"
              className="h-8 text-xs bg-destructive/10 hover:bg-destructive/20 text-destructive border border-destructive/25 shadow-none"
              onClick={handleReject}
            >
              Reject
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ReviewPage() {
  const { data: items, isLoading, isError, error, refetch } = useReviewList();
  const reviewAction = useReviewAction();
  const [view, setView] = useState<ViewMode>("grid");

  const pendingCount = (items ?? []).length;

  const handleApprove = useCallback(
    (id: string) => reviewAction.mutate({ id, action: "approve" }),
    [reviewAction],
  );

  const handleReject = useCallback(
    (id: string, reason: string) => reviewAction.mutate({ id, action: "reject", reason }),
    [reviewAction],
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
            {!isLoading && pendingCount > 0 && (
              <Badge variant="secondary" className="text-xs">
                {pendingCount} pending
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
      <div className="p-6 max-w-6xl mx-auto space-y-4">
        {isLoading ? (
          view === "list" ? (
            <TableSkeleton rows={6} cols={4} />
          ) : (
            <CardSkeleton count={3} columns={3} />
          )
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : pendingCount === 0 ? (
          <EmptyState
            icon={CheckCircle2}
            title="All clear"
            description="All submissions have been reviewed. New items will appear here when agents or components are submitted."
          />
        ) : view === "list" ? (
          <div className="animate-in rounded-md border border-border overflow-hidden">
            {(items ?? []).map((item: ReviewItem) => (
              <ReviewRow
                key={item.id}
                item={item}
                onApprove={handleApprove}
                onReject={handleReject}
              />
            ))}
          </div>
        ) : (
          <div className="animate-in grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(items ?? []).map((item: ReviewItem) => (
              <ReviewCard
                key={item.id}
                item={item}
                onApprove={handleApprove}
                onReject={handleReject}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
