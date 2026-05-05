"use client";

import Link from "next/link";
import { Play, Loader2, CheckCircle2, XCircle, Clock } from "lucide-react";
import { useRegistryList, useInsightReports, useGenerateInsight } from "@/hooks/use-api";
import type { RegistryItem, InsightReportListItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layouts/page-header";
import { CardSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

function StatusBadge({ status }: { status: InsightReportListItem["status"] }) {
  switch (status) {
    case "completed":
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-success bg-success/10 px-2 py-0.5 rounded-full">
          <CheckCircle2 className="h-3 w-3" /> Completed
        </span>
      );
    case "running":
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-info bg-info/10 px-2 py-0.5 rounded-full">
          <Loader2 className="h-3 w-3 animate-spin" /> Running
        </span>
      );
    case "pending":
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
          <Clock className="h-3 w-3" /> Pending
        </span>
      );
    case "failed":
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-destructive bg-destructive/10 px-2 py-0.5 rounded-full">
          <XCircle className="h-3 w-3" /> Failed
        </span>
      );
  }
}

function AgentInsightCard({ agent }: { agent: RegistryItem }) {
  const { data: reports } = useInsightReports(agent.id);
  const generateInsight = useGenerateInsight();

  const latest = (reports ?? [])[0] as InsightReportListItem | undefined;
  const reportCount = (reports ?? []).length;

  return (
    <div className="rounded-md border border-border bg-card p-4 flex flex-col gap-3 hover:bg-muted/30 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-[family-name:var(--font-display)] text-sm font-semibold truncate">
            {agent.name}
          </h3>
          {agent.description && (
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
              {agent.description}
            </p>
          )}
        </div>
        {latest && <StatusBadge status={latest.status} />}
      </div>

      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        {latest ? (
          <>
            <span className="font-[family-name:var(--font-mono)] tabular-nums">
              {latest.sessions_analyzed} sessions
            </span>
            <span>
              {new Date(latest.created_at).toLocaleDateString()}
            </span>
            {reportCount > 1 && (
              <span>{reportCount} reports</span>
            )}
          </>
        ) : (
          <span>No reports generated yet</span>
        )}
      </div>

      <div className="flex items-center gap-2 mt-auto pt-1">
        {latest?.status === "completed" && (
          <Link href={`/insights/${latest.id}`} className="flex-1">
            <Button variant="outline" size="sm" className="w-full h-7 text-xs">
              View Report
            </Button>
          </Link>
        )}
        {(latest?.status === "pending" || latest?.status === "running") && (
          <div className="flex-1 flex items-center gap-2 px-2 py-1 rounded bg-muted/50 border border-border">
            <Loader2 className="h-3 w-3 animate-spin text-info" />
            <span className="text-xs text-muted-foreground">
              {latest.status === "pending" ? "Queued..." : "Generating report..."}
            </span>
          </div>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs gap-1"
          disabled={generateInsight.isPending || latest?.status === "pending" || latest?.status === "running"}
          onClick={() => generateInsight.mutate({ agentId: agent.id })}
        >
          <Play className="h-3 w-3" />
          Generate
        </Button>
      </div>
    </div>
  );
}

export default function InsightsPage() {
  const { data: agents, isLoading, isError } = useRegistryList("agents");

  return (
    <>
      <PageHeader title="Agent Insights" />

      <div className="p-4 sm:p-6">
        {isLoading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <CardSkeleton key={i} />
            ))}
          </div>
        )}

        {isError && <ErrorState message="Failed to load agents" />}

        {!isLoading && !isError && (!agents || agents.length === 0) && (
          <EmptyState
            title="No agents registered"
            description="Register agents in the registry to generate performance insights."
          />
        )}

        {!isLoading && !isError && agents && agents.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {agents.map((agent) => (
              <AgentInsightCard key={agent.id} agent={agent} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
