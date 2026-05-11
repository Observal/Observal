// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { use, useState, useEffect } from "react";
import { FlaskConical, Zap } from "lucide-react";
import { useEvalScorecards, useEvalAggregate, useRegistryItem, useEvalRun, useEvalPenalties, useAgentEvaluatedSessions, useSessionEfficiency } from "@/hooks/use-api";
import type { RegistryItem, Scorecard } from "@/lib/types";
import { AgentAggregateChart } from "@/components/dashboard/agent-aggregate-chart";
import { DimensionRadar } from "@/components/dashboard/dimension-radar";
import { PenaltyAccordion } from "@/components/dashboard/penalty-accordion";
import { EfficiencyMetrics } from "@/components/dashboard/efficiency-metrics";
import { SessionDAG } from "@/components/dashboard/session-dag";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton, ChartSkeleton, DetailSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { ScoreOverview } from "@/components/dashboard/score-overview";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function gradeColor(grade: string | undefined): string {
  if (!grade) return "text-muted-foreground";
  const g = grade.toUpperCase();
  if (g.startsWith("A")) return "text-success";
  if (g.startsWith("B")) return "text-info";
  if (g.startsWith("C")) return "text-warning";
  return "text-destructive";
}


export default function EvalDetailPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = use(params);
  const { data: agent } = useRegistryItem("agents", agentId);
  const { data: scorecards, isLoading, isError, error, refetch } = useEvalScorecards(agentId);
  const { data: aggregate, isLoading: aggLoading } = useEvalAggregate(agentId);
  const { data: evaluatedSessions, isLoading: sessionsLoading } = useAgentEvaluatedSessions(agentId);
  const runEval = useEvalRun();

  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  // Auto-select first session when sessions load (using derived state to avoid effect)
  const defaultSessionId = evaluatedSessions?.[0]?.session_id ?? null;
  const activeSessionId = selectedSessionId ?? defaultSessionId;

  const { data: efficiency, isLoading: effLoading } = useSessionEfficiency(activeSessionId ?? undefined);

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
        <Tabs defaultValue="evaluation" className="animate-in">
          <TabsList>
            <TabsTrigger value="evaluation">Evaluation</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
          </TabsList>

          {/* Evaluation Tab - Merged Correctness & Efficiency */}
          <TabsContent value="evaluation" className="mt-6">
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              {/* LEFT SECTION: CORRECTNESS */}
              <div className="rounded-lg border border-border bg-card">
                <div className="border-b border-border px-5 py-3 flex items-center gap-2">
                  <FlaskConical className="h-4 w-4 text-muted-foreground" />
                  <h2 className="text-sm font-semibold">Correctness</h2>
                </div>
                <div className="p-5 space-y-6">
                  {/* Latest Evaluation */}
                  {latest ? (
                    <section className="animate-in">
                      <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                        Latest Evaluation
                      </h3>
                      <div className="rounded-md border border-border p-4">
                        <ScoreOverview
                          displayScore={latest.display_score ?? 0}
                          grade={latest.grade ?? "-"}
                          dimensionScores={latest.dimension_scores ?? {}}
                          penaltyCount={latest.penalty_count}
                        />
                        {latest.version && (
                          <p className="text-xs text-muted-foreground mt-3 pt-3 border-t border-border">
                            Version: <span className="font-[family-name:var(--font-mono)]">v{latest.version}</span>
                          </p>
                        )}
                      </div>
                    </section>
                  ) : (
                    <EmptyState
                      icon={FlaskConical}
                      title="No evaluation yet"
                      description="Run an eval to see correctness scores."
                      onAction={() => runEval.mutate({ agentId })}
                      actionLabel="Run Eval"
                    />
                  )}

                  {/* Dimension Radar */}
                  {latest?.dimension_scores && (
                    <section className="animate-in stagger-1">
                      <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                        Dimension Radar
                      </h3>
                      <div className="rounded-md border border-border p-3">
                        <DimensionRadar dimensionScores={latest.dimension_scores} />
                      </div>
                    </section>
                  )}

                  {/* Recommendations */}
                  {latest && (latest.scoring_recommendations ?? []).length > 0 && (
                    <section className="animate-in stagger-2">
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

                  {/* Penalties */}
                  {latestPenalties && latestPenalties.length > 0 && (
                    <section className="animate-in stagger-3">
                      <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                        Penalties ({latestPenalties.length})
                      </h3>
                      <PenaltyAccordion penalties={latestPenalties} />
                    </section>
                  )}
                </div>
              </div>

              {/* RIGHT SECTION: EFFICIENCY */}
              <div className="rounded-lg border border-border bg-card">
                <div className="border-b border-border px-5 py-3 flex items-center gap-2">
                  <Zap className="h-4 w-4 text-muted-foreground" />
                  <h2 className="text-sm font-semibold">Efficiency</h2>
                </div>
                <div className="p-5 space-y-6">
                  {/* Session Selector */}
                  <div className="space-y-3">
                    <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      Evaluated Session
                    </h3>
                    {sessionsLoading ? (
                      <div className="h-9 w-full animate-pulse bg-muted rounded-md" />
                    ) : evaluatedSessions && evaluatedSessions.length > 0 ? (
                      <Select value={activeSessionId ?? ""} onValueChange={setSelectedSessionId}>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder="Select a session to view efficiency" />
                        </SelectTrigger>
                        <SelectContent>
                          {evaluatedSessions.map((session) => {
                            const startTime = session.start_time ? new Date(session.start_time) : null;
                            const firstPrompt = session.first_prompt || "";
                            const promptPreview = firstPrompt.slice(0, 60);

                            return (
                              <SelectItem key={session.session_id} value={session.session_id}>
                                <div className="flex flex-col gap-0.5 py-1">
                                  <div className="flex items-center gap-2">
                                    {startTime ? (
                                      <span className="text-foreground text-xs font-medium">
                                        {startTime.toLocaleDateString()} {startTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                      </span>
                                    ) : (
                                      <span className="text-muted-foreground text-xs">Unknown time</span>
                                    )}
                                    {session.event_count && session.event_count > 0 && (
                                      <span className="text-muted-foreground text-[10px]">
                                        ({session.event_count} events)
                                      </span>
                                    )}
                                  </div>
                                  {promptPreview && (
                                    <span className="text-muted-foreground text-[11px] italic">
                                      &ldquo;{promptPreview}{firstPrompt.length > 60 ? "..." : ""}&rdquo;
                                    </span>
                                  )}
                                </div>
                              </SelectItem>
                            );
                          })}
                        </SelectContent>
                      </Select>
                    ) : (
                      <EmptyState
                        icon={Zap}
                        title="No evaluated sessions"
                        description="Run an eval to see efficiency metrics."
                        onAction={() => runEval.mutate({ agentId })}
                        actionLabel="Run Eval"
                      />
                    )}
                  </div>

                  {/* Efficiency Content */}
                  {activeSessionId && (
                    <>
                      {effLoading ? (
                        <DetailSkeleton />
                      ) : efficiency && !efficiency.error ? (
                        <div className="space-y-6">
                          {/* Efficiency Metrics */}
                          <section className="animate-in">
                            <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                              Metrics
                            </h3>
                            <EfficiencyMetrics data={efficiency} />
                          </section>

                          {/* Session DAG */}
                          <section className="animate-in stagger-1">
                            <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                              Session DAG
                            </h3>
                            {efficiency.dag ? (
                              <SessionDAG dag={efficiency.dag} />
                            ) : (
                              <EmptyState
                                icon={Zap}
                                title="No DAG data"
                                description="DAG visualization is not available for this session."
                              />
                            )}
                          </section>
                        </div>
                      ) : (
                        <EmptyState
                          icon={Zap}
                          title="No efficiency data"
                          description={efficiency?.error || "Efficiency metrics are not available for this session yet."}
                        />
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          </TabsContent>

          {/* History Tab */}
          <TabsContent value="history" className="mt-6">
            <div className="space-y-6">
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
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}
