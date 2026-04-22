"use client";

import { use } from "react";
import { FlaskConical } from "lucide-react";
import { useEvalScorecards, useEvalAggregate, useRegistryItem, useEvalRun, useEvalPenalties } from "@/hooks/use-api";
import type { RegistryItem, Scorecard } from "@/lib/types";
import { AgentAggregateChart } from "@/components/dashboard/agent-aggregate-chart";
import { DimensionRadar } from "@/components/dashboard/dimension-radar";
import { PenaltyAccordion } from "@/components/dashboard/penalty-accordion";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton, ChartSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

function gradeColor(grade: string | undefined): string {
  if (!grade) return "text-muted-foreground";
  const g = grade.toUpperCase();
  if (g.startsWith("A")) return "text-success";
  if (g.startsWith("B")) return "text-info";
  if (g.startsWith("C")) return "text-warning";
  return "text-destructive";
}

function gradeBg(grade: string | undefined): string {
  if (!grade) return "bg-muted";
  const g = grade.toUpperCase();
  if (g.startsWith("A")) return "bg-success/10";
  if (g.startsWith("B")) return "bg-info/10";
  if (g.startsWith("C")) return "bg-warning/10";
  return "bg-destructive/10";
}

export default function EvalDetailPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = use(params);
  const { data: agent } = useRegistryItem("agents", agentId);
  const { data: scorecards, isLoading, isError, error, refetch } = useEvalScorecards(agentId);
  const { data: aggregate, isLoading: aggLoading } = useEvalAggregate(agentId);
  const runEval = useEvalRun();

  const a = agent as RegistryItem | undefined;
  const cards = scorecards ?? [];
  const latest = cards[0] as Scorecard | undefined;

  const { data: latestPenalties } = useEvalPenalties(latest?.id);

  const agentName = a?.name ?? agentId.slice(0, 8);

  return (
    <>
      <PageHeader
        title={agentName}
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Eval", href: "/eval" },
          { label: agentName },
        ]}
        actionButtonsRight={
          <Button
            size="sm"
            onClick={() => runEval.mutate({ agentId })}
            disabled={runEval.isPending}
          >
            {runEval.isPending ? "Running..." : "Run Eval"}
          </Button>
        }
      />
      <div className="p-6 w-full mx-auto space-y-6">
        {/* 2-column layout */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left: 2/3 — Chart + History */}
          <div className="lg:col-span-2 space-y-6">
            {/* Aggregate Chart */}
            {aggLoading ? (
              <ChartSkeleton />
            ) : aggregate ? (
              <section className="animate-in">
                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                  Score Over Time
                </h3>
                <div className="rounded-md border border-border p-4">
                  <AgentAggregateChart data={aggregate} />
                </div>
              </section>
            ) : null}

            {/* Scorecard History */}
            <section className="animate-in stagger-2">
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                Scorecard History
              </h3>
              {isLoading ? (
                <TableSkeleton rows={5} cols={5} />
              ) : isError ? (
                <ErrorState message={error?.message} onRetry={() => refetch()} />
              ) : cards.length === 0 ? (
                <EmptyState
                  icon={FlaskConical}
                  title="No scorecards yet"
                  description="Run an eval to generate scores for this agent."
                  onAction={() => runEval.mutate({ agentId })}
                  actionLabel="Run Eval"
                />
              ) : (
                <div className="overflow-x-auto rounded-md border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="h-8 text-xs">Date</TableHead>
                        <TableHead className="h-8 text-xs">Version</TableHead>
                        <TableHead className="h-8 text-xs">Score</TableHead>
                        <TableHead className="h-8 text-xs">Grade</TableHead>
                        <TableHead className="h-8 text-xs text-right">Penalties</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {cards.map((sc: Scorecard) => (
                        <TableRow key={sc.id}>
                          <TableCell className="py-1.5 text-xs tabular-nums">
                            {sc.created_at ? new Date(sc.created_at).toLocaleDateString() : "-"}
                          </TableCell>
                          <TableCell className="py-1.5 text-xs text-muted-foreground font-[family-name:var(--font-mono)]">
                            {sc.version ? `v${sc.version}` : "-"}
                          </TableCell>
                          <TableCell className="py-1.5 text-xs font-[family-name:var(--font-mono)] tabular-nums">
                            {sc.display_score?.toFixed(1) ?? sc.overall_score?.toFixed(1) ?? "-"}
                          </TableCell>
                          <TableCell className="py-1.5">
                            <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${gradeColor(sc.grade ?? sc.overall_grade)}`}>
                              {sc.grade ?? sc.overall_grade ?? "-"}
                            </Badge>
                          </TableCell>
                          <TableCell className="py-1.5 text-xs text-muted-foreground text-right tabular-nums">
                            {sc.penalty_count ?? 0}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </section>
          </div>

          {/* Right: 1/3 — Score Summary */}
          <div className="space-y-6">
            {/* Current Grade */}
            {latest && (
              <section className="animate-in stagger-1">
                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                  Current Score
                </h3>
                <div className="rounded-md border border-border p-4 space-y-3">
                  <div className="flex items-center gap-4">
                    <div className={`flex items-center justify-center w-14 h-14 rounded-md ${gradeBg(latest.grade)}`}>
                      <span className={`text-2xl font-bold font-[family-name:var(--font-display)] ${gradeColor(latest.grade)}`}>
                        {latest.grade ?? "-"}
                      </span>
                    </div>
                    <div>
                      {latest.display_score != null && (
                        <p className="text-lg font-semibold font-[family-name:var(--font-mono)] tabular-nums">
                          {latest.display_score.toFixed(1)}<span className="text-xs text-muted-foreground">/10</span>
                        </p>
                      )}
                      {latest.version && (
                        <p className="text-xs text-muted-foreground">v{latest.version}</p>
                      )}
                    </div>
                  </div>
                </div>
              </section>
            )}

            {/* Dimension Radar */}
            {latest?.dimension_scores && (
              <section className="animate-in stagger-2">
                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                  Dimensions
                </h3>
                <div className="rounded-md border border-border p-2">
                  <DimensionRadar dimensionScores={latest.dimension_scores} />
                </div>
              </section>
            )}

            {/* Recommendations */}
            {latest && (latest.scoring_recommendations ?? []).length > 0 && (
              <section className="animate-in stagger-3">
                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                  Recommendations
                </h3>
                <ul className="space-y-2">
                  {(latest.scoring_recommendations ?? []).map((r: string, i: number) => (
                    <li key={i} className="flex gap-2 text-xs text-muted-foreground">
                      <span className="text-foreground shrink-0">-</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        </div>

        {/* Penalties */}
        {latestPenalties && latestPenalties.length > 0 && (
          <>
            <Separator />
            <section className="animate-in stagger-4">
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                Penalties ({latestPenalties.length})
              </h3>
              <PenaltyAccordion penalties={latestPenalties} />
            </section>
          </>
        )}
      </div>
    </>
  );
}
