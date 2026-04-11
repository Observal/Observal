"use client";

import { useState, useCallback } from "react";
import { CheckCircle2, X } from "lucide-react";
import { useReviewList, useReviewAction } from "@/hooks/use-api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/layouts/page-header";
import { CardSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

function ReviewCard({ item, onApprove, onReject }: {
  item: any;
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

      <div className="text-xs text-muted-foreground">
        {item.submitted_at || item.created_at
          ? new Date(item.submitted_at ?? item.created_at).toLocaleDateString()
          : ""}
      </div>

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
          className="h-7 text-xs flex-1 bg-success hover:bg-success/90 text-success-foreground"
          onClick={() => onApprove(item.id)}
        >
          Approve
        </Button>
        <Button
          variant="destructive"
          size="sm"
          className="h-7 text-xs flex-1"
          onClick={handleReject}
        >
          {showRejectInput ? "Confirm" : "Reject"}
        </Button>
      </div>
    </div>
  );
}

export default function ReviewPage() {
  const { data: items, isLoading, isError, error, refetch } = useReviewList();
  const reviewAction = useReviewAction();

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
          !isLoading && pendingCount > 0 ? (
            <Badge variant="secondary" className="text-xs">
              {pendingCount} pending
            </Badge>
          ) : undefined
        }
      />
      <div className="p-6 max-w-6xl mx-auto space-y-4">
        {isLoading ? (
          <CardSkeleton count={3} columns={3} />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : pendingCount === 0 ? (
          <EmptyState
            icon={CheckCircle2}
            title="All clear"
            description="All submissions have been reviewed. New items will appear here when agents or components are submitted."
          />
        ) : (
          <div className="animate-in grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(items ?? []).map((item: any) => (
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
