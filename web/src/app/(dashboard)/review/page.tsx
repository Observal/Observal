"use client";

import { useState } from "react";
import { useReviewList, useReviewAction } from "@/hooks/use-api";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/registry/status-badge";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { ClipboardCheck } from "lucide-react";

const TYPES = [
  "all",
  "mcp",
  "agent",
  "tool",
  "skill",
  "hook",
  "prompt",
  "sandbox",
  "graphrag",
];
const TYPE_LABELS: Record<string, string> = {
  all: "All",
  mcp: "MCP Servers",
  agent: "Agents",
  tool: "Tools",
  skill: "Skills",
  hook: "Hooks",
  prompt: "Prompts",
  sandbox: "Sandboxes",
  graphrag: "GraphRAGs",
};

interface ReviewItem {
  id: string;
  name?: string;
  type?: string;
  listing_type?: string;
  submitted_by?: string;
  submitted_at?: string;
  created_at?: string;
  status?: string;
}

export default function ReviewPage() {
  const [typeFilter, setTypeFilter] = useState("all");
  const [rejectId, setRejectId] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const { data: items, isLoading } = useReviewList(
    typeFilter === "all" ? undefined : typeFilter,
  );
  const { mutate: act, isPending } = useReviewAction();

  const handleApprove = (id: string) => act({ id, action: "approve" });
  const handleReject = () => {
    if (rejectId) {
      act(
        { id: rejectId, action: "reject", reason },
        {
          onSuccess: () => {
            setRejectId(null);
            setReason("");
          },
        },
      );
    }
  };

  const reviewItems = items as ReviewItem[] | undefined;

  return (
    <DashboardShell>
      <PageHeader
        title="Review Queue"
        breadcrumbs={[
          { label: "Home", href: "/" },
          { label: "Review" },
        ]}
      />
      <DashboardContent>
        <div className="flex flex-col gap-3">
          <Tabs value={typeFilter} onValueChange={setTypeFilter}>
            <TabsList className="h-8">
              {TYPES.map((t) => (
                <TabsTrigger key={t} value={t} className="text-xs">
                  {TYPE_LABELS[t]}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>

          {isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : !reviewItems?.length ? (
            <div className="flex flex-col items-center justify-center rounded-md border border-dashed py-16">
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-muted">
                <ClipboardCheck className="h-5 w-5 text-muted-foreground" />
              </div>
              <p className="mt-3 text-sm font-medium">No pending submissions</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Submissions will appear here when users submit new registry
                items for review.
              </p>
            </div>
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="h-9 px-3 text-xs">Name</TableHead>
                    <TableHead className="h-9 px-3 text-xs">Type</TableHead>
                    <TableHead className="h-9 px-3 text-xs">
                      Submitted By
                    </TableHead>
                    <TableHead className="h-9 px-3 text-xs">Date</TableHead>
                    <TableHead className="h-9 px-3 text-xs">Status</TableHead>
                    <TableHead className="h-9 px-3 text-xs text-right">
                      Actions
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reviewItems.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="px-3 py-2 text-sm font-medium">
                        {item.name ?? "—"}
                      </TableCell>
                      <TableCell className="px-3 py-2">
                        <Badge variant="outline" className="text-xs">
                          {item.type ?? item.listing_type ?? "—"}
                        </Badge>
                      </TableCell>
                      <TableCell className="px-3 py-2 text-sm">
                        {item.submitted_by ?? "—"}
                      </TableCell>
                      <TableCell className="px-3 py-2 text-xs text-muted-foreground">
                        {item.submitted_at || item.created_at
                          ? new Date(
                              (item.submitted_at ?? item.created_at)!,
                            ).toLocaleDateString()
                          : "—"}
                      </TableCell>
                      <TableCell className="px-3 py-2">
                        <StatusBadge status={item.status ?? "pending"} />
                      </TableCell>
                      <TableCell className="px-3 py-2 text-right">
                        <div className="flex justify-end gap-1">
                          <Button
                            size="sm"
                            className="h-7 bg-dark-green text-white hover:bg-dark-green/90"
                            disabled={isPending}
                            onClick={() => handleApprove(item.id)}
                          >
                            Approve
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            className="h-7"
                            disabled={isPending}
                            onClick={() => setRejectId(item.id)}
                          >
                            Reject
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      </DashboardContent>

      <Dialog
        open={!!rejectId}
        onOpenChange={(open) => {
          if (!open) setRejectId(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject Submission</DialogTitle>
          </DialogHeader>
          <Textarea
            placeholder="Reason for rejection…"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectId(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={isPending || !reason.trim()}
              onClick={handleReject}
            >
              Reject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DashboardShell>
  );
}
