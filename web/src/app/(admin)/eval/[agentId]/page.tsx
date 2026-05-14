// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Bot,
  ExternalLink,
  FlaskConical,
  GitBranch,
  MessageSquareWarning,
  Sparkles,
  Wrench,
  Zap,
} from "lucide-react";
import {
  useEvalScorecards,
  useEvalAggregate,
  useRegistryItem,
  useEvalRun,
  useEvalPenalties,
  useReliabilityReport,
} from "@/hooks/use-api";
import { eval_ } from "@/lib/api";
import type {
  RegistryItem,
  ReliabilityDagEdge,
  ReliabilityDagNode,
  ReliabilityReport,
  Scorecard,
  TracePenalty,
} from "@/lib/types";
import { AgentAggregateChart } from "@/components/dashboard/agent-aggregate-chart";
import { DimensionRadar } from "@/components/dashboard/dimension-radar";
import { PenaltyAccordion } from "@/components/dashboard/penalty-accordion";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton, ChartSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const DIM_LABELS: { key: string; label: string }[] = [
  { key: "goal_completion", label: "Goal Completion" },
  { key: "tool_efficiency", label: "Tool Efficiency" },
  { key: "tool_failures", label: "Dependency Failures" },
  { key: "factual_grounding", label: "Factual Grounding" },
  { key: "thought_process", label: "Thought Process" },
  { key: "adversarial_robustness", label: "Adversarial Robustness" },
];

type AttributionKey =
  | "agent"
  | "mcp_tool"
  | "prompt_injection"
  | "waste"
  | "user_ambiguity";

type AttributionRecord = Record<AttributionKey, number>;

const ATTRIBUTION_META: Record<
  AttributionKey,
  {
    label: string;
    description: string;
    color: string;
    icon: typeof Bot;
  }
> = {
  agent: {
    label: "Agent",
    description: "Goal misses, weak reasoning, or unsupported claims produced by the agent itself.",
    color: "text-red-400",
    icon: Bot,
  },
  mcp_tool: {
    label: "Dependency",
    description: "Tool outages, dependency call failures, or brittle tool handling that blocked progress.",
    color: "text-orange-400",
    icon: Wrench,
  },
  prompt_injection: {
    label: "Prompt Injection",
    description: "Adversarial prompts, evaluator overrides, or other unsafe prompting patterns.",
    color: "text-fuchsia-400",
    icon: MessageSquareWarning,
  },
  waste: {
    label: "Waste",
    description: "Duplicate work, dead-end cycles, redundant reads, or output that never gets used.",
    color: "text-amber-400",
    icon: Zap,
  },
  user_ambiguity: {
    label: "User Ambiguity",
    description: "Ambiguous requests that made the task underspecified or unstable.",
    color: "text-slate-300",
    icon: AlertTriangle,
  },
};

function gradeTextColor(grade: string | undefined): string {
  if (!grade) return "text-muted-foreground";
  const g = grade.toUpperCase();
  if (g.startsWith("A")) return "text-emerald-400";
  if (g.startsWith("B")) return "text-sky-400";
  if (g.startsWith("C")) return "text-amber-400";
  return "text-red-400";
}

function gradeBorder(grade: string | undefined): string {
  if (!grade) return "border-border bg-card";
  const g = grade.toUpperCase();
  if (g.startsWith("A")) return "border-emerald-400/30 bg-emerald-400/5";
  if (g.startsWith("B")) return "border-sky-400/30 bg-sky-400/5";
  if (g.startsWith("C")) return "border-amber-400/30 bg-amber-400/5";
  return "border-red-400/30 bg-red-400/5";
}

function histGradeColor(grade: string | undefined): string {
  if (!grade) return "text-muted-foreground";
  const g = grade.toUpperCase();
  if (g.startsWith("A")) return "text-emerald-400";
  if (g.startsWith("B")) return "text-sky-400";
  if (g.startsWith("C")) return "text-amber-400";
  return "text-red-400";
}

function barFill(score: number): string {
  if (score >= 80) return "bg-emerald-400";
  if (score >= 60) return "bg-sky-400";
  if (score >= 40) return "bg-amber-400";
  return "bg-red-400";
}

function formatCategoryLabel(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatEventName(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function attributionColor(key: AttributionKey): string {
  return ATTRIBUTION_META[key].color;
}

function emptyAttribution(): AttributionRecord {
  return {
    agent: 0,
    mcp_tool: 0,
    prompt_injection: 0,
    waste: 0,
    user_ambiguity: 0,
  };
}

function computeFallbackAttribution(penalties: TracePenalty[]): AttributionRecord {
  const attr = emptyAttribution();
  const wasteKeywords = ["waste", "duplicate", "unused", "revert", "redundant"];
  for (const penalty of penalties) {
    const dimension = String(penalty.dimension || "").toLowerCase();
    const event = String(penalty.event_name || "").toLowerCase();
    const amount = Math.abs(Number(penalty.amount) || 0);
    if (wasteKeywords.some((keyword) => event.includes(keyword))) {
      attr.waste += amount;
      continue;
    }
    if (dimension === "tool_failures") {
      attr.mcp_tool += amount;
      continue;
    }
    if (dimension === "adversarial_robustness") {
      attr.prompt_injection += amount;
      continue;
    }
    if (dimension === "goal_completion" || dimension === "factual_grounding" || dimension === "thought_process" || dimension === "tool_efficiency") {
      attr.agent += amount;
      continue;
    }
    attr.agent += amount;
  }
  return attr;
}

function getAttribution(report: ReliabilityReport | undefined, penalties: TracePenalty[]): AttributionRecord {
  if (!report?.penalty_attribution) return computeFallbackAttribution(penalties);
  return {
    agent: Number(report.penalty_attribution.agent || 0),
    mcp_tool: Number(report.penalty_attribution.mcp_tool || 0),
    prompt_injection: Number(report.penalty_attribution.prompt_injection || 0),
    waste: Number(report.penalty_attribution.waste || 0),
    user_ambiguity: Number(report.penalty_attribution.user_ambiguity || 0),
  };
}

function dominantKey(report: ReliabilityReport | undefined, attr: AttributionRecord): AttributionKey | null {
  const reported = report?.dominant_failure;
  if (reported && reported in attr) {
    return reported as AttributionKey;
  }
  const total = Object.values(attr).reduce((sum, value) => sum + value, 0);
  if (total === 0) return null;
  return (Object.entries(attr) as [AttributionKey, number][])
    .sort(([, a], [, b]) => b - a)[0][0];
}

function categoryForPenalty(penalty: TracePenalty): AttributionKey {
  const dimension = String(penalty.dimension || "").toLowerCase();
  const event = String(penalty.event_name || "").toLowerCase();
  if (["waste", "duplicate", "unused", "revert", "redundant"].some((keyword) => event.includes(keyword))) {
    return "waste";
  }
  if (dimension === "tool_failures") return "mcp_tool";
  if (dimension === "adversarial_robustness") return "prompt_injection";
  return "agent";
}

function topPenaltyEvidence(
  penalties: TracePenalty[],
  category: AttributionKey,
  maxItems = 2,
): string[] {
  return penalties
    .filter((penalty) => categoryForPenalty(penalty) === category)
    .sort((left, right) => Math.abs(Number(right.amount || 0)) - Math.abs(Number(left.amount || 0)))
    .slice(0, maxItems)
    .map((penalty) => String(penalty.evidence || penalty.event_name || "").trim())
    .filter(Boolean);
}

function topPenaltyNames(
  penalties: TracePenalty[],
  category: AttributionKey,
  maxItems = 3,
): string[] {
  const unique = new Set<string>();
  for (const penalty of penalties
    .filter((item) => categoryForPenalty(item) === category)
    .sort((left, right) => Math.abs(Number(right.amount || 0)) - Math.abs(Number(left.amount || 0)))) {
    const label = formatEventName(String(penalty.event_name || "Penalty"));
    if (!unique.has(label)) unique.add(label);
    if (unique.size >= maxItems) break;
  }
  return [...unique];
}

function shareOfTotal(amount: number, attr: AttributionRecord): number {
  const total = Object.values(attr).reduce((sum, value) => sum + value, 0);
  return total > 0 ? (amount / total) * 100 : 0;
}

function DimensionRow({ label, score }: { label: string; score: number | null }) {
  if (score === null || score === undefined) {
    return (
      <div className="flex items-center gap-3 py-2.5">
        <span className="w-48 text-xs text-muted-foreground shrink-0">{label}</span>
        <div className="flex-1 h-1.5 bg-muted rounded-full" />
        <span className="w-10 text-right text-xs text-muted-foreground font-mono">n/a</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-3 py-2.5">
      <span className="w-48 text-xs text-muted-foreground shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${barFill(score)}`}
          style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
        />
      </div>
      <span
        className={`w-10 text-right text-xs font-mono font-semibold ${
          score >= 80
            ? "text-emerald-400"
            : score >= 60
              ? "text-sky-400"
              : score >= 40
                ? "text-amber-400"
                : "text-red-400"
        }`}
      >
        {score.toFixed(0)}
      </span>
    </div>
  );
}

function AttributionFlowGraph({
  attribution,
  penalties,
}: {
  attribution: AttributionRecord;
  penalties: TracePenalty[];
}) {
  const categories: AttributionKey[] = ["agent", "mcp_tool", "prompt_injection", "waste"];
  const active = categories.filter((key) => attribution[key] > 0);
  if (active.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-muted-foreground">
        No penalties were applied, so there is no failure flow to visualize for this run.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {active.map((key) => {
          const Icon = ATTRIBUTION_META[key].icon;
          return (
            <div
              key={key}
              className="rounded-lg border border-border bg-card/60 px-4 py-3"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Icon className={`h-4 w-4 ${attributionColor(key)}`} />
                  <span className="text-sm font-medium text-foreground">
                    {formatCategoryLabel(key)}
                  </span>
                </div>
                <span className={`text-sm font-mono font-semibold ${attributionColor(key)}`}>
                  -{attribution[key].toFixed(0)}
                </span>
              </div>
              <div className="mt-3 h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full ${barFill(100 - attribution[key])}`}
                  style={{ width: `${Math.max(10, shareOfTotal(attribution[key], attribution))}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {topPenaltyNames(penalties, key, 2).join(" • ") || "No detailed penalties"}
              </p>
            </div>
          );
        })}
      </div>
      <div className="rounded-lg border border-border bg-card/40 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {active.map((key, index) => (
            <div key={key} className="flex items-center gap-2">
              <span className={`font-medium ${attributionColor(key)}`}>{formatCategoryLabel(key)}</span>
              {index < active.length - 1 && <GitBranch className="h-3 w-3 text-muted-foreground/60" />}
            </div>
          ))}
          <span className="ml-auto font-mono text-foreground">
            Total penalty load: -{active.reduce((sum, key) => sum + attribution[key], 0).toFixed(0)}
          </span>
        </div>
      </div>
    </div>
  );
}

function TraceDagSvg({
  nodes,
  edges,
}: {
  nodes: ReliabilityDagNode[];
  edges: ReliabilityDagEdge[];
}) {
  if (!nodes.length) {
    return <p className="text-xs text-muted-foreground">No DAG data available for this scorecard.</p>;
  }

  const width = 920;
  const nodeRadius = 18;
  const depthStep = 88;
  const grouped: Record<number, ReliabilityDagNode[]> = {};

  for (const node of nodes) {
    const depth = node.depth ?? 0;
    if (!grouped[depth]) grouped[depth] = [];
    grouped[depth].push(node);
  }

  const maxDepth = Math.max(...nodes.map((node) => node.depth ?? 0));
  const height = (maxDepth + 2) * depthStep;
  const pos: Record<string, { x: number; y: number }> = {};

  for (const [depthString, group] of Object.entries(grouped)) {
    const depth = Number(depthString);
    const count = group.length;
    group.forEach((node, index) => {
      pos[node.span_id] = {
        x: ((index + 1) * width) / (count + 1),
        y: depth * depthStep + depthStep / 2 + 20,
      };
    });
  }

  function nodeColor(status: string): string {
    if (status === "error" || status === "failure") return "#f87171";
    if (status === "waste") return "#fbbf24";
    if (status === "injection") return "#e879f9";
    if (status === "recovery") return "#38bdf8";
    return "#34d399";
  }

  return (
    <div className="overflow-x-auto">
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="font-mono text-xs">
        <defs>
          <marker id="eval-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L0,6 L8,3 z" fill="#6b7280" />
          </marker>
        </defs>
        {edges.map((edge, index) => {
          const src = pos[edge.src];
          const dst = pos[edge.dst];
          if (!src || !dst) return null;
          const dx = dst.x - src.x;
          const dy = dst.y - src.y;
          const len = Math.sqrt(dx * dx + dy * dy) || 1;
          const x1 = src.x + (dx / len) * nodeRadius;
          const y1 = src.y + (dy / len) * nodeRadius;
          const x2 = dst.x - (dx / len) * (nodeRadius + 6);
          const y2 = dst.y - (dy / len) * (nodeRadius + 6);
          return (
            <line
              key={`${edge.src}-${edge.dst}-${index}`}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke={edge.confidence === "low" ? "#4b5563" : "#6b7280"}
              strokeWidth={1.5}
              strokeDasharray={edge.confidence === "low" ? "5 3" : undefined}
              markerEnd="url(#eval-arrow)"
            />
          );
        })}
        {nodes.map((node) => {
          const p = pos[node.span_id];
          if (!p) return null;
          const color = nodeColor(node.status);
          const label = (node.name || node.span_id).slice(0, 12);
          return (
            <g key={node.span_id}>
              <circle
                cx={p.x}
                cy={p.y}
                r={nodeRadius}
                fill={`${color}22`}
                stroke={color}
                strokeWidth={node.is_cycle ? 2 : 1.5}
                strokeDasharray={node.is_cycle ? "4 2" : undefined}
              />
              <text
                x={p.x}
                y={p.y + 4}
                textAnchor="middle"
                fontSize={9}
                fill={color}
              >
                {label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function ScoreExplanation({
  scorecardId,
  dominantFailure,
}: {
  scorecardId: string;
  dominantFailure: string | null;
}) {
  const [explanation, setExplanation] = useState<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "unavailable">("loading");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let retries = 0;
    let cancelled = false;

    const poll = async () => {
      if (retries >= 10) {
        if (!cancelled) setStatus("unavailable");
        if (pollRef.current) clearInterval(pollRef.current);
        return;
      }
      retries += 1;
      const response = await eval_.scorecardExplanation(scorecardId);
      if (cancelled) return;
      if (response.status === "ready" && response.explanation) {
        setExplanation(response.explanation);
        setStatus("ready");
        if (pollRef.current) clearInterval(pollRef.current);
      } else if (response.status === "unavailable") {
        setStatus("unavailable");
        if (pollRef.current) clearInterval(pollRef.current);
      }
    };

    poll();
    pollRef.current = setInterval(poll, 2000);

    return () => {
      cancelled = true;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [scorecardId]);

  const borderClass =
    dominantFailure === "agent"
      ? "border-red-400"
      : dominantFailure === "mcp_tool"
        ? "border-orange-400"
        : dominantFailure === "prompt_injection"
          ? "border-fuchsia-400"
          : dominantFailure === "waste"
            ? "border-amber-400"
            : "border-border";

  if (status === "loading") {
    return (
      <div className="space-y-2 py-1">
        <div className="h-4 w-full animate-pulse bg-muted rounded" />
        <div className="h-4 w-4/5 animate-pulse bg-muted rounded" />
        <div className="h-4 w-3/5 animate-pulse bg-muted rounded" />
      </div>
    );
  }

  if (status === "unavailable" || !explanation) {
    return (
      <p className="text-sm text-muted-foreground">
        Explanation is not available for this scorecard yet. The penalty evidence below still reflects the actual scored signals.
      </p>
    );
  }

  return (
    <p className={`border-l-2 pl-3 text-sm leading-relaxed ${borderClass}`}>
      {explanation}
    </p>
  );
}

function AttributionDiagnosticCard({
  category,
  amount,
  attribution,
  penalties,
  isDominant,
}: {
  category: AttributionKey;
  amount: number;
  attribution: AttributionRecord;
  penalties: TracePenalty[];
  isDominant: boolean;
}) {
  const IconComponent = ATTRIBUTION_META[category].icon;
  const evidence = topPenaltyEvidence(penalties, category, 2);
  const eventNames = topPenaltyNames(penalties, category, 3);
  const share = shareOfTotal(amount, attribution);

  return (
    <div
      className={`rounded-lg border p-4 space-y-3 transition-colors ${
        isDominant
          ? "border-current bg-card shadow-[inset_0_0_0_1px_rgba(255,255,255,0.04)]"
          : "border-border bg-card"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <IconComponent className={`h-4 w-4 ${attributionColor(category)}`} />
            <span className="text-sm font-semibold text-foreground">
              {ATTRIBUTION_META[category].label}
            </span>
            {isDominant && (
              <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${attributionColor(category)} border-current`}>
                Dominant
              </Badge>
            )}
          </div>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {ATTRIBUTION_META[category].description}
          </p>
        </div>
        <div className="text-right shrink-0">
          <div className={`text-2xl font-mono font-bold ${amount > 0 ? attributionColor(category) : "text-muted-foreground"}`}>
            {amount > 0 ? `-${amount.toFixed(0)}` : "—"}
          </div>
          <div className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">
            {share > 0 ? `${share.toFixed(0)}% share` : "No hit"}
          </div>
        </div>
      </div>

      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full ${barFill(100 - amount)}`}
          style={{ width: `${Math.max(6, share)}%` }}
        />
      </div>

      {eventNames.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {eventNames.map((name) => (
            <Badge key={name} variant="outline" className="text-[10px] px-1.5 py-0 text-muted-foreground">
              {name}
            </Badge>
          ))}
        </div>
      ) : null}

      {evidence.length > 0 ? (
        <div className="space-y-1.5">
          {evidence.map((item, index) => (
            <p key={`${category}-${index}`} className="text-xs leading-relaxed text-muted-foreground">
              {item}
            </p>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">This category did not materially contribute to the score.</p>
      )}
    </div>
  );
}

export default function EvalDetailPage({
  params,
}: {
  params: Promise<{ agentId: string }>;
}) {
  const { agentId } = use(params);
  const { data: agent } = useRegistryItem("agents", agentId);
  const {
    data: scorecards,
    isLoading,
    isError,
    error,
    refetch,
  } = useEvalScorecards(agentId);
  const { data: aggregate, isLoading: aggLoading } = useEvalAggregate(agentId);
  const runEval = useEvalRun();

  const registryAgent = agent as RegistryItem | undefined;
  const cards = scorecards ?? [];
  const latest = cards[0] as Scorecard | undefined;
  const latestTraceId = latest?.trace_id;

  const { data: rawPenalties } = useEvalPenalties(latest?.id);
  const penalties = (rawPenalties ?? []) as TracePenalty[];
  const reliability = useReliabilityReport(latestTraceId);

  const agentName = registryAgent?.name ?? agentId.slice(0, 8);
  const dimScores = latest?.dimension_scores ?? {};
  const grade = latest?.grade ?? latest?.overall_grade;
  const score = latest?.display_score ?? latest?.overall_score ?? 0;
  const attribution = getAttribution(reliability.data, penalties);
  const dominant = dominantKey(reliability.data, attribution);
  const activeAttribution: AttributionKey[] = ["agent", "mcp_tool", "prompt_injection", "waste"];
  const latestWarnings = latest?.warnings ?? [];

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
        <Tabs defaultValue="report" className="animate-in">
          <TabsList>
            <TabsTrigger value="report">Eval Report</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
          </TabsList>

          <TabsContent value="report" className="mt-6 space-y-6">
            {isLoading ? (
              <div className="space-y-4">
                {[...Array(3)].map((_, index) => (
                  <div key={index} className="h-20 animate-pulse bg-muted rounded-lg" />
                ))}
              </div>
            ) : !latest ? (
              <EmptyState
                icon={FlaskConical}
                title="No evaluation yet"
                description="Run an eval to see the scorecard and penalty attribution."
                onAction={() => runEval.mutate({ agentId })}
                actionLabel="Run Eval"
              />
            ) : (
              <>
                <div className={`rounded-lg border p-5 flex flex-wrap items-center gap-6 ${gradeBorder(grade)}`}>
                  <div className="text-center min-w-[48px]">
                    <div className={`text-5xl font-bold font-mono leading-none ${gradeTextColor(grade)}`}>
                      {grade ?? "—"}
                    </div>
                    <div className="text-[10px] text-muted-foreground mt-1 uppercase tracking-wider">
                      Grade
                    </div>
                  </div>

                  <div className="w-px h-12 bg-border hidden sm:block" />

                  <div className="text-center min-w-[64px]">
                    <div className={`text-4xl font-bold font-mono leading-none ${gradeTextColor(grade)}`}>
                      {score.toFixed(1)}
                    </div>
                    <div className="text-[10px] text-muted-foreground mt-1 uppercase tracking-wider">
                      Score
                    </div>
                  </div>

                  <div className="w-px h-12 bg-border hidden sm:block" />

                  <div className="text-center min-w-[48px]">
                    <div className="text-4xl font-bold font-mono leading-none text-red-400">
                      {latest.penalty_count ?? 0}
                    </div>
                    <div className="text-[10px] text-muted-foreground mt-1 uppercase tracking-wider">
                      Penalties
                    </div>
                  </div>

                  {latest.version && (
                    <div className="ml-auto text-right">
                      <div className="text-[10px] text-muted-foreground uppercase tracking-wider">
                        Version
                      </div>
                      <div className="text-sm font-mono mt-0.5">v{latest.version}</div>
                    </div>
                  )}
                </div>

                <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.9fr)]">
                  <div className="space-y-6">
                    <div className="rounded-lg border border-border bg-card">
                      <div className="border-b border-border px-5 py-3 flex items-center gap-2">
                        <Sparkles className="h-4 w-4 text-muted-foreground" />
                        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          Why Did This Score?
                        </h3>
                      </div>
                      <div className="px-5 py-4 space-y-4">
                        <ScoreExplanation
                          scorecardId={latest.id}
                          dominantFailure={reliability.data?.dominant_failure ?? dominant}
                        />
                        {latestWarnings.length > 0 && (
                          <div className="rounded-md border border-amber-400/30 bg-amber-400/5 px-3 py-2">
                            <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-300">
                              Evaluation Warnings
                            </p>
                            <div className="mt-2 space-y-1.5">
                              {latestWarnings.slice(0, 3).map((warning) => (
                                <p key={warning} className="text-xs text-muted-foreground">
                                  {warning}
                                </p>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="space-y-3">
                      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Penalty Attribution
                      </h3>
                      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                        {activeAttribution.map((category) => (
                          <AttributionDiagnosticCard
                            key={category}
                            category={category}
                            amount={attribution[category]}
                            attribution={attribution}
                            penalties={penalties}
                            isDominant={dominant === category}
                          />
                        ))}
                      </div>
                    </div>

                    <div className="rounded-lg border border-border bg-card">
                      <div className="border-b border-border px-5 py-3">
                        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          Penalty Flow Graph
                        </h3>
                      </div>
                      <div className="px-5 py-4">
                        <AttributionFlowGraph attribution={attribution} penalties={penalties} />
                      </div>
                    </div>

                    {penalties.length > 0 && (
                      <div className="rounded-lg border border-border bg-card">
                        <div className="border-b border-border px-5 py-3">
                          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                            Penalty Detail ({penalties.length})
                          </h3>
                        </div>
                        <div className="p-4">
                          <PenaltyAccordion penalties={penalties} />
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="space-y-6">
                    {Object.keys(dimScores).length > 0 && (
                      <div className="rounded-lg border border-border bg-card">
                        <div className="border-b border-border px-5 py-3">
                          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                            Dimension Snapshot
                          </h3>
                        </div>
                        <div className="px-5 py-4">
                          <DimensionRadar dimensionScores={dimScores} />
                          <div className="mt-4 divide-y divide-border">
                            {DIM_LABELS.map(({ key, label }) => (
                              <DimensionRow
                                key={key}
                                label={label}
                                score={dimScores[key] != null ? dimScores[key] : null}
                              />
                            ))}
                          </div>
                        </div>
                      </div>
                    )}

                    <div className="rounded-lg border border-border bg-card">
                      <button
                        className="w-full flex items-center justify-between px-5 py-3"
                        type="button"
                      >
                        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          Trace DAG
                        </span>
                        {reliability.data?.trace_dag?.nodes?.length ? (
                          <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-muted-foreground">
                            {reliability.data.trace_dag.nodes.length} nodes
                          </Badge>
                        ) : null}
                      </button>
                      <div className="border-t border-border px-5 py-4">
                        {reliability.isLoading ? (
                          <div className="h-40 animate-pulse rounded-lg bg-muted" />
                        ) : reliability.data?.trace_dag ? (
                          <TraceDagSvg
                            nodes={reliability.data.trace_dag.nodes}
                            edges={reliability.data.trace_dag.edges}
                          />
                        ) : (
                          <p className="text-sm text-muted-foreground">
                            DAG data is not available for this trace yet.
                          </p>
                        )}
                      </div>
                    </div>

                    {(latest.scoring_recommendations ?? []).length > 0 && (
                      <div className="rounded-lg border border-border bg-card">
                        <div className="border-b border-border px-5 py-3">
                          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                            Recommendations
                          </h3>
                        </div>
                        <ul className="px-5 py-4 space-y-3">
                          {(latest.scoring_recommendations ?? []).map((recommendation, index) => (
                            <li key={`${index}-${recommendation}`} className="flex gap-2.5 text-sm">
                              <span className="text-muted-foreground shrink-0 mt-0.5 font-mono text-xs">
                                {index + 1}.
                              </span>
                              <span className="text-muted-foreground">{recommendation}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </TabsContent>

          <TabsContent value="history" className="mt-6 space-y-6">
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

            <section className="animate-in stagger-2">
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                Scorecard History
              </h3>
              {isLoading ? (
                <TableSkeleton rows={5} cols={6} />
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
                        <TableHead className="h-8 text-xs text-right">Report</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {cards.map((scorecard) => {
                        const traceId = scorecard.trace_id;
                        const date = scorecard.evaluated_at ?? scorecard.created_at;
                        return (
                          <TableRow key={scorecard.id}>
                            <TableCell className="py-1.5 text-xs tabular-nums">
                              {date ? new Date(date).toLocaleDateString() : "—"}
                            </TableCell>
                            <TableCell className="py-1.5 text-xs text-muted-foreground font-mono">
                              {scorecard.version ? `v${scorecard.version}` : "—"}
                            </TableCell>
                            <TableCell className="py-1.5 text-xs font-mono tabular-nums">
                              {scorecard.display_score?.toFixed(1) ??
                                scorecard.overall_score?.toFixed(1) ??
                                "—"}
                            </TableCell>
                            <TableCell className="py-1.5">
                              <Badge
                                variant="outline"
                                className={`text-[10px] px-1.5 py-0 ${histGradeColor(scorecard.grade ?? scorecard.overall_grade)}`}
                              >
                                {scorecard.grade ?? scorecard.overall_grade ?? "—"}
                              </Badge>
                            </TableCell>
                            <TableCell className="py-1.5 text-xs text-muted-foreground text-right tabular-nums">
                              {scorecard.penalty_count ?? 0}
                            </TableCell>
                            <TableCell className="py-1.5 text-right">
                              {traceId ? (
                                <Link
                                  href={`/eval/traces/${encodeURIComponent(traceId)}/reliability`}
                                  className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                                  title="View reliability report"
                                >
                                  <ExternalLink className="h-3 w-3" />
                                </Link>
                              ) : (
                                <span className="text-muted-foreground text-[10px]">—</span>
                              )}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </section>
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}
