"use client";

import Link from "next/link";
import { FlaskConical, Play, AlertTriangle } from "lucide-react";
import { useRegistryList, useEvalScorecards, useEvalRun } from "@/hooks/use-api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import type { RegistryItem, Scorecard } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layouts/page-header";
import { CardSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

function gradeColor(grade: string | undefined): string {
  if (!grade) return "bg-muted text-muted-foreground";
  const g = grade.toUpperCase();
  if (g.startsWith("A")) return "bg-success/15 text-success";
  if (g.startsWith("B")) return "bg-info/15 text-info";
  if (g.startsWith("C")) return "bg-warning/15 text-warning";
  return "bg-destructive/15 text-destructive";
}

function AgentEvalCard({ agent }: { agent: RegistryItem }) {
  const { data: scorecards } = useEvalScorecards(agent.id);
  const runEval = useEvalRun();

  const latest = (scorecards ?? [])[0] as Scorecard | undefined;
  const evalCount = (scorecards ?? []).length;

  return (
    <div className="rounded-md border border-border bg-card p-4 flex flex-col gap-3 hover:bg-muted/30 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <Link
          href={`/eval/${agent.id}`}
          className="font-[family-name:var(--font-display)] text-sm font-semibold hover:text-primary-accent transition-colors truncate"
        >
          {agent.name}
        </Link>
        {latest?.grade && (
          <span className={`text-xs font-semibold font-[family-name:var(--font-mono)] px-1.5 py-0.5 rounded ${gradeColor(latest.grade)}`}>
            {latest.grade}
          </span>
        )}
      </div>

      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        {latest?.display_score != null && (
          <span className="font-[family-name:var(--font-mono)] tabular-nums">
            {latest.display_score.toFixed(1)}/10
          </span>
        )}
        {evalCount > 0 && (
          <span>{evalCount} eval{evalCount !== 1 ? "s" : ""}</span>
        )}
        {!latest && (
          <span>No evaluations yet</span>
        )}
      </div>

      <div className="flex items-center gap-2 mt-auto pt-1">
        <Link href={`/eval/${agent.id}`} className="flex-1">
          <Button variant="outline" size="sm" className="w-full h-7 text-xs">
            View Details
          </Button>
        </Link>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs gap-1"
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
      <div className="p-6 w-full mx-auto space-y-4">
        {!configLoading && !evalConfigured && (
          <div className="animate-in flex items-start gap-3 rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-3">
            <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
            <div className="space-y-1">
              <p className="text-sm font-medium text-amber-600 dark:text-amber-400">
                No eval model configured
              </p>
              <p className="text-xs text-muted-foreground">
                Set <code className="font-[family-name:var(--font-mono)] bg-muted px-1 rounded">EVAL_MODEL_NAME</code> in
                your <code className="font-[family-name:var(--font-mono)] bg-muted px-1 rounded">.env</code> to
                enable LLM-as-judge scoring. Without it, evaluations use heuristic scoring only. See the setup guide for supported providers (AWS Bedrock, OpenAI-compatible).
              </p>
            </div>
          </div>
        )}

        <p className="text-sm text-muted-foreground animate-in">
          Run evaluations against deployed agents to score quality, efficiency, and reliability.
        </p>

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
