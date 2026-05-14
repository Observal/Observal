// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import Link from "next/link";
import { FlaskConical, Play, AlertTriangle, Bot, Wrench, MessageSquareWarning, Zap } from "lucide-react";
import { useRegistryList, useEvalScorecards, useEvalRun } from "@/hooks/use-api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import type { RegistryItem, Scorecard } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/layouts/page-header";
import { CardSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

// ── Helpers ────────────────────────────────────────────────────────────────────

function gradeTextColor(grade: string | undefined): string {
  if (!grade) return "text-muted-foreground";
  const g = grade.toUpperCase();
  if (g.startsWith("A")) return "text-emerald-400";
  if (g.startsWith("B")) return "text-sky-400";
  if (g.startsWith("C")) return "text-amber-400";
  return "text-red-400";
}

function gradeBg(grade: string | undefined): string {
  if (!grade) return "bg-muted/20 border-muted";
  const g = grade.toUpperCase();
  if (g.startsWith("A")) return "bg-emerald-400/10 border-emerald-400/30";
  if (g.startsWith("B")) return "bg-sky-400/10 border-sky-400/30";
  if (g.startsWith("C")) return "bg-amber-400/10 border-amber-400/30";
  return "bg-red-400/10 border-red-400/30";
}

// ── Weakness tags derived from dimension scores ────────────────────────────────

const AGENT_DIMS = ["goal_completion", "factual_grounding", "thought_process"];
const DEPENDENCY_DIMS = ["tool_failures"];
const SEC_DIMS = ["adversarial_robustness"];
const WASTE_DIMS = ["tool_efficiency"];

interface WeaknessTag {
  label: string;
  icon: React.ElementType;
  color: string;
}

function getWeaknessTags(dimensionScores?: Record<string, number>): WeaknessTag[] {
  if (!dimensionScores) return [];

  const avg = (dims: string[]): number | null => {
    const vals = dims.map((d) => dimensionScores[d]).filter((v) => v != null);
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  };

  const tags: WeaknessTag[] = [];

  const agentAvg = avg(AGENT_DIMS);
  if (agentAvg != null && agentAvg < 70)
    tags.push({ label: "Agent failures", icon: Bot, color: "text-red-400 border-red-400/30 bg-red-400/5" });

  const dependencyAvg = avg(DEPENDENCY_DIMS);
  if (dependencyAvg != null && dependencyAvg < 70)
    tags.push({ label: "Dependency issues", icon: Wrench, color: "text-orange-400 border-orange-400/30 bg-orange-400/5" });

  const secAvg = avg(SEC_DIMS);
  if (secAvg != null && secAvg < 70)
    tags.push({ label: "Prompt injection risk", icon: MessageSquareWarning, color: "text-purple-400 border-purple-400/30 bg-purple-400/5" });

  const wasteAvg = avg(WASTE_DIMS);
  if (wasteAvg != null && wasteAvg < 60)
    tags.push({ label: "Inefficiency", icon: Zap, color: "text-amber-400 border-amber-400/30 bg-amber-400/5" });

  return tags;
}

// ── Agent eval card ────────────────────────────────────────────────────────────

function AgentEvalCard({ agent }: { agent: RegistryItem }) {
  const { data: scorecards } = useEvalScorecards(agent.id);
  const runEval = useEvalRun();

  const latest = (scorecards ?? [])[0] as Scorecard | undefined;
  const evalCount = (scorecards ?? []).length;
  const grade = latest?.grade ?? latest?.overall_grade;
  const score = latest?.display_score ?? latest?.overall_score;
  const weaknesses = getWeaknessTags(latest?.dimension_scores);

  return (
    <div className="rounded-lg border border-border bg-card flex flex-col gap-0 hover:border-muted-foreground/30 transition-colors overflow-hidden">
      {/* Header */}
      <div className="px-4 pt-4 pb-3 flex items-start justify-between gap-2">
        <Link
          href={`/eval/${agent.id}`}
          className="font-[family-name:var(--font-display)] text-sm font-semibold hover:text-primary-accent transition-colors truncate leading-tight"
        >
          {agent.name}
        </Link>
        {grade ? (
          <div
            className={`flex items-center gap-2 px-2.5 py-1 rounded border text-xs font-mono font-bold shrink-0 ${gradeBg(grade)}`}
          >
            <span className={gradeTextColor(grade)}>{grade}</span>
            {score != null && (
              <span className="text-muted-foreground font-normal">
                {score.toFixed(1)}
              </span>
            )}
          </div>
        ) : (
          <Badge variant="outline" className="text-[10px] text-muted-foreground shrink-0">
            No eval
          </Badge>
        )}
      </div>

      {/* Penalty attribution tags */}
      {weaknesses.length > 0 ? (
        <div className="px-4 pb-3 flex flex-wrap gap-1.5">
          {weaknesses.map((w) => (
            <span
              key={w.label}
              className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border ${w.color}`}
            >
              <w.icon className="h-2.5 w-2.5" />
              {w.label}
            </span>
          ))}
        </div>
      ) : latest?.dimension_scores ? (
        <div className="px-4 pb-3">
          <span className="text-[10px] text-emerald-400 font-medium">
            ✓ No significant weaknesses detected
          </span>
        </div>
      ) : latest ? (
        <div className="px-4 pb-3 text-[10px] text-muted-foreground">
          {evalCount} eval{evalCount !== 1 ? "s" : ""} · {latest.penalty_count ?? 0} penalties
        </div>
      ) : (
        <div className="px-4 pb-3 text-[10px] text-muted-foreground">
          No evaluations yet
        </div>
      )}

      {/* Dimension mini-bars */}
      {latest?.dimension_scores && (
        <div className="px-4 pb-3 space-y-1">
          {[
            { key: "goal_completion", label: "Goal", color: "bg-emerald-400" },
            { key: "tool_failures", label: "Dependency", color: "bg-orange-400" },
            { key: "tool_efficiency", label: "Efficiency", color: "bg-sky-400" },
          ].map(({ key, label, color }) => {
            const val = latest.dimension_scores?.[key];
            if (val == null) return null;
            return (
              <div key={key} className="flex items-center gap-2">
                <span className="text-[10px] text-muted-foreground w-14 shrink-0">{label}</span>
                <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      val >= 70 ? color : "bg-red-400"
                    }`}
                    style={{ width: `${Math.min(100, val)}%` }}
                  />
                </div>
                <span className="text-[10px] font-mono text-muted-foreground w-7 text-right">
                  {val.toFixed(0)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Actions */}
      <div className="mt-auto border-t border-border px-4 py-2.5 flex items-center gap-2 bg-muted/20">
        <Link href={`/eval/${agent.id}`} className="flex-1">
          <Button variant="outline" size="sm" className="w-full h-7 text-xs">
            View Report
          </Button>
        </Link>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs gap-1 shrink-0"
          onClick={() => runEval.mutate({ agentId: agent.id })}
          disabled={runEval.isPending}
        >
          <Play className="h-3 w-3" />
          {runEval.isPending ? "Running..." : "Run"}
        </Button>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function EvalPage() {
  const { data: agents, isLoading, isError, error, refetch } = useRegistryList("agents");
  const { evalConfigured, loading: configLoading } = useDeploymentConfig();

  return (
    <>
      <PageHeader
        title="Agent Evaluations"
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Eval" },
        ]}
      />
      <div className="p-6 w-full mx-auto space-y-5">
        {!configLoading && !evalConfigured && (
          <div className="animate-in flex items-start gap-3 rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-3">
            <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
            <div className="space-y-1">
              <p className="text-sm font-medium text-amber-600 dark:text-amber-400">
                No eval model configured
              </p>
              <p className="text-xs text-muted-foreground">
                Set{" "}
                <code className="font-[family-name:var(--font-mono)] bg-muted px-1 rounded">
                  EVAL_MODEL_NAME
                </code>{" "}
                in your{" "}
                <code className="font-[family-name:var(--font-mono)] bg-muted px-1 rounded">
                  .env
                </code>{" "}
                to enable LLM-as-judge scoring. Without it, evaluations use heuristic scoring
                only.
              </p>
            </div>
          </div>
        )}

        {/* Legend */}
        <div className="flex flex-wrap items-center gap-4 text-[10px] text-muted-foreground">
          <span className="font-medium uppercase tracking-wider">Weakness indicators:</span>
          <span className="flex items-center gap-1">
            <Bot className="h-3 w-3 text-red-400" />
            <span className="text-red-400">Agent failures</span>
          </span>
          <span className="flex items-center gap-1">
            <Wrench className="h-3 w-3 text-orange-400" />
            <span className="text-orange-400">Dependency issues</span>
          </span>
          <span className="flex items-center gap-1">
            <MessageSquareWarning className="h-3 w-3 text-purple-400" />
            <span className="text-purple-400">Prompt injection risk</span>
          </span>
          <span className="flex items-center gap-1">
            <Zap className="h-3 w-3 text-amber-400" />
            <span className="text-amber-400">Inefficiency</span>
          </span>
        </div>

        <div className={!evalConfigured ? "opacity-60 pointer-events-none" : ""}>
          {isLoading ? (
            <CardSkeleton count={6} columns={3} />
          ) : isError ? (
            <ErrorState message={error?.message} onRetry={() => refetch()} />
          ) : (agents ?? []).length === 0 ? (
            <EmptyState
              icon={FlaskConical}
              title="No agents to evaluate"
              description="Submit an agent to the registry to run evaluations against it."
              actionLabel="Browse Agents"
              actionHref="/agents"
            />
          ) : (
            <div className="animate-in stagger-1 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {(agents ?? []).map((a: RegistryItem) => (
                <AgentEvalCard key={a.id} agent={a} />
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
