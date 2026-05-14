// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
//
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { use, useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Zap,
  ShieldAlert,
} from "lucide-react";
import { useReliabilityReport } from "@/hooks/use-api";
import { eval_ } from "@/lib/api";
import type {
  ReliabilityTimelineNode,
  ReliabilityDagNode,
  ReliabilityDagEdge,
  WasteCluster,
} from "@/lib/types";
import { PageHeader } from "@/components/layouts/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/shared/empty-state";
import { Drawer } from "vaul";

// ── Color helpers ──────────────────────────────────────────────────────────────

function scoreColor(score: number): string {
  if (score >= 90) return "text-emerald-400";
  if (score >= 70) return "text-amber-400";
  if (score >= 50) return "text-orange-400";
  return "text-red-400";
}

function scoreBg(score: number): string {
  if (score >= 90) return "bg-emerald-400/10 border-emerald-400/30";
  if (score >= 70) return "bg-amber-400/10 border-amber-400/30";
  if (score >= 50) return "bg-orange-400/10 border-orange-400/30";
  return "bg-red-400/10 border-red-400/30";
}

function barFill(score: number): string {
  if (score >= 90) return "bg-emerald-400";
  if (score >= 70) return "bg-amber-400";
  if (score >= 50) return "bg-orange-400";
  return "bg-red-400";
}

// ── Status styles ──────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, { dot: string; label: string; border: string }> = {
  success:   { dot: "bg-emerald-400", label: "text-emerald-400", border: "border-emerald-400/40" },
  failure:   { dot: "bg-red-400",     label: "text-red-400",     border: "border-red-400/40" },
  waste:     { dot: "bg-amber-400",   label: "text-amber-400",   border: "border-amber-400/40" },
  injection: { dot: "bg-purple-400",  label: "text-purple-400",  border: "border-purple-400/40" },
  recovery:  { dot: "bg-blue-400",    label: "text-blue-400",    border: "border-blue-400/40" },
};

function getStatusStyle(status: string) {
  return STATUS_STYLES[status] ?? STATUS_STYLES.success;
}

// ── Latency display ────────────────────────────────────────────────────────────

function fmtLatency(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtCheckType(ct: string): string {
  return ct.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Dimension bar ──────────────────────────────────────────────────────────────

function DimensionBar({ label, score }: { label: string; score: number | null }) {
  if (score === null || score === undefined) {
    return (
      <div className="flex items-center gap-3 py-1.5">
        <span className="w-48 text-sm text-muted-foreground shrink-0">{label}</span>
        <div className="flex-1 h-2 bg-muted rounded-sm" />
        <span className="w-12 text-right text-xs text-muted-foreground font-mono">n/a</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="w-48 text-sm text-muted-foreground shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-muted rounded-sm overflow-hidden">
        <div
          className={`h-full rounded-sm ${barFill(score)}`}
          style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
        />
      </div>
      <span className={`w-12 text-right text-sm font-mono font-medium ${scoreColor(score)}`}>
        {score.toFixed(0)}
      </span>
    </div>
  );
}

// ── Trace DAG SVG ──────────────────────────────────────────────────────────────

function TraceDagSvg({
  nodes,
  edges,
}: {
  nodes: ReliabilityDagNode[];
  edges: ReliabilityDagEdge[];
}) {
  if (!nodes.length) return <p className="text-xs text-muted-foreground">No DAG data.</p>;

  const SVG_WIDTH = 900;
  const NODE_R = 18;
  const DEPTH_STEP = 80;

  // Group nodes by depth
  const byDepth: Record<number, ReliabilityDagNode[]> = {};
  for (const n of nodes) {
    const d = n.depth ?? 0;
    if (!byDepth[d]) byDepth[d] = [];
    byDepth[d].push(n);
  }
  const maxDepth = Math.max(...nodes.map((n) => n.depth ?? 0));
  const SVG_HEIGHT = (maxDepth + 2) * DEPTH_STEP;

  // Compute positions
  const pos: Record<string, { x: number; y: number }> = {};
  for (const [depthStr, grp] of Object.entries(byDepth)) {
    const depth = Number(depthStr);
    const count = grp.length;
    grp.forEach((n, i) => {
      pos[n.span_id] = {
        x: ((i + 1) * SVG_WIDTH) / (count + 1),
        y: depth * DEPTH_STEP + DEPTH_STEP / 2 + 20,
      };
    });
  }

  // Node color by status
  function nodeColor(status: string): string {
    if (status === "error" || status === "failure") return "#f87171"; // red-400
    if (status === "waste") return "#fbbf24";   // amber-400
    if (status === "injection") return "#c084fc"; // purple-400
    return "#34d399"; // emerald-400
  }

  return (
    <div className="overflow-x-auto">
      <svg
        width={SVG_WIDTH}
        height={SVG_HEIGHT}
        className="font-mono text-xs"
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
      >
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L0,6 L8,3 z" fill="#6b7280" />
          </marker>
          <marker id="arrow-low" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L0,6 L8,3 z" fill="#4b5563" />
          </marker>
        </defs>

        {/* Edges */}
        {edges.map((e, i) => {
          const src = pos[e.src];
          const dst = pos[e.dst];
          if (!src || !dst) return null;
          const isLow = e.confidence === "low";
          // Offset line endpoints to node edge
          const dx = dst.x - src.x;
          const dy = dst.y - src.y;
          const len = Math.sqrt(dx * dx + dy * dy) || 1;
          const x1 = src.x + (dx / len) * NODE_R;
          const y1 = src.y + (dy / len) * NODE_R;
          const x2 = dst.x - (dx / len) * (NODE_R + 6);
          const y2 = dst.y - (dy / len) * (NODE_R + 6);
          return (
            <line
              key={i}
              x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={isLow ? "#4b5563" : "#6b7280"}
              strokeWidth={1.5}
              strokeDasharray={isLow ? "5 3" : undefined}
              markerEnd={isLow ? "url(#arrow-low)" : "url(#arrow)"}
            />
          );
        })}

        {/* Nodes */}
        {nodes.map((n) => {
          const p = pos[n.span_id];
          if (!p) return null;
          const color = nodeColor(n.status);
          const label = (n.name || n.span_id).slice(0, 12);
          return (
            <g key={n.span_id}>
              <circle
                cx={p.x}
                cy={p.y}
                r={NODE_R}
                fill={`${color}22`}
                stroke={color}
                strokeWidth={n.is_cycle ? 2 : 1.5}
                strokeDasharray={n.is_cycle ? "4 2" : undefined}
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

// ── Evidence Drawer ────────────────────────────────────────────────────────────

type DrawerContent = {
  type: "span" | "check" | "penalty";
  spanId?: string;
  checkIndex?: number;
  penaltyEventName?: string;
  scorecardId?: string;
  title?: string;
  detail?: string;
};

function EvidenceDrawer({
  open,
  onClose,
  content,
}: {
  open: boolean;
  onClose: () => void;
  content: DrawerContent | null;
}) {
  const [explanation, setExplanation] = useState<string | null>(null);
  const [explStatus, setExplStatus] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const retriesRef = useRef(0);

  const fetchExplanation = useCallback(async () => {
    if (!content?.scorecardId || content.checkIndex === undefined) return;
    retriesRef.current = 0;
    setExplStatus("loading");
    setExplanation(null);

    const poll = async () => {
      if (retriesRef.current >= 10) {
        clearInterval(pollRef.current);
        setExplStatus("unavailable");
        return;
      }
      retriesRef.current += 1;
      const res = await eval_.checkExplanation(
        content.scorecardId!,
        String(content.checkIndex),
      );
      if (res.status === "ready" && res.explanation) {
        clearInterval(pollRef.current);
        setExplanation(res.explanation);
        setExplStatus("ready");
      } else if (res.status === "unavailable") {
        clearInterval(pollRef.current);
        setExplStatus("unavailable");
      }
    };

    await poll();
    if (explStatus !== "ready" && explStatus !== "unavailable") {
      pollRef.current = setInterval(poll, 2000);
    }
  }, [content, explStatus]);

  useEffect(() => {
    if (open && content?.type === "check" && content.scorecardId !== undefined) {
      fetchExplanation();
    }
    return () => {
      clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, content?.checkIndex, content?.scorecardId]);

  useEffect(() => {
    if (!open) {
      clearInterval(pollRef.current);
      setExplanation(null);
      setExplStatus("idle");
    }
  }, [open]);

  return (
    <Drawer.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Drawer.Portal>
        <Drawer.Overlay className="fixed inset-0 bg-black/50 z-40" />
        <Drawer.Content className="fixed bottom-0 left-0 right-0 z-50 bg-card border-t border-border rounded-t max-h-[60vh] overflow-auto">
          <div className="mx-auto w-12 h-1 bg-muted rounded-full mt-3 mb-4" />
          <div className="px-6 pb-8">
            {content && (
              <>
                <h3 className="text-sm font-semibold mb-1">{content.title ?? "Evidence"}</h3>
                {content.spanId && (
                  <p className="text-xs font-mono text-muted-foreground mb-3 break-all">
                    span: {content.spanId}
                  </p>
                )}
                {content.detail && (
                  <p className="text-sm text-muted-foreground mb-4 leading-relaxed">
                    {content.detail}
                  </p>
                )}
                {content.type === "check" && content.scorecardId !== undefined && (
                  <div className="mt-2">
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                      Fix Suggestion
                    </p>
                    {explStatus === "loading" && (
                      <div className="space-y-2">
                        <div className="h-4 w-3/4 animate-pulse bg-muted rounded" />
                        <div className="h-4 w-1/2 animate-pulse bg-muted rounded" />
                      </div>
                    )}
                    {explStatus === "ready" && explanation && (
                      <p className="text-sm leading-relaxed border-l-2 border-emerald-400 pl-3">
                        {explanation}
                      </p>
                    )}
                    {explStatus === "unavailable" && (
                      <p className="text-xs text-muted-foreground">Fix suggestion unavailable.</p>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  );
}

// ── Root Cause Analysis ────────────────────────────────────────────────────────

function RootCauseSection({
  scorecardId,
  dominantFailure,
}: {
  scorecardId: string;
  dominantFailure: string | null;
}) {
  const [explanation, setExplanation] = useState<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "unavailable">("loading");
  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const retriesRef = useRef(0);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      if (retriesRef.current >= 10) {
        clearInterval(pollRef.current);
        if (!cancelled) setStatus("unavailable");
        return;
      }
      retriesRef.current += 1;
      const res = await eval_.scorecardExplanation(scorecardId);
      if (cancelled) return;
      if (res.status === "ready" && res.explanation) {
        clearInterval(pollRef.current);
        setExplanation(res.explanation);
        setStatus("ready");
      } else if (res.status === "unavailable") {
        clearInterval(pollRef.current);
        setStatus("unavailable");
      }
    };

    poll();
    pollRef.current = setInterval(poll, 2000);

    return () => {
      cancelled = true;
      clearInterval(pollRef.current);
    };
  }, [scorecardId]);

  const borderColor = (() => {
    if (!dominantFailure) return "border-muted";
    if (dominantFailure === "agent") return "border-red-400";
    if (dominantFailure === "waste") return "border-amber-400";
    if (dominantFailure === "prompt_injection") return "border-purple-400";
    if (dominantFailure === "mcp_tool") return "border-orange-400";
    return "border-muted";
  })();

  if (status === "loading") {
    return (
      <div className="space-y-2 py-2">
        <div className="h-4 w-full animate-pulse bg-muted rounded" />
        <div className="h-4 w-4/5 animate-pulse bg-muted rounded" />
        <div className="h-4 w-3/5 animate-pulse bg-muted rounded" />
      </div>
    );
  }
  if (status === "unavailable" || !explanation) {
    return (
      <p className="text-sm text-muted-foreground">
        Root cause analysis unavailable for this trace.
      </p>
    );
  }
  return (
    <p className={`text-sm leading-relaxed border-l-2 pl-3 ${borderColor}`}>
      {explanation}
    </p>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function ReliabilityReportPage({
  params,
}: {
  params: Promise<{ traceId: string }>;
}) {
  const { traceId } = use(params);
  const { data: report, isLoading, isError } = useReliabilityReport(traceId);

  const [dagOpen, setDagOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerContent, setDrawerContent] = useState<DrawerContent | null>(null);

  function openSpanDrawer(node: ReliabilityTimelineNode) {
    setDrawerContent({
      type: "span",
      spanId: node.span_id,
      title: node.name || node.span_id,
      detail: node.description || `Status: ${node.status_label} — latency: ${fmtLatency(node.latency_ms)}`,
    });
    setDrawerOpen(true);
  }

  function openPenaltyDrawer(penalty: Record<string, unknown>) {
    setDrawerContent({
      type: "penalty",
      title: String(penalty.event_name ?? "Penalty"),
      detail: String(penalty.evidence ?? ""),
    });
    setDrawerOpen(true);
  }

  if (isLoading) {
    return (
      <>
        <PageHeader
          title="Reliability Report"
          breadcrumbs={[
            { label: "Eval", href: "/eval" },
            { label: "Traces" },
            { label: traceId.slice(0, 12) },
            { label: "Reliability Report" },
          ]}
        />
        <div className="p-6 space-y-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-16 animate-pulse bg-muted rounded" />
          ))}
        </div>
      </>
    );
  }

  if (isError || !report) {
    return (
      <>
        <PageHeader
          title="Reliability Report"
          breadcrumbs={[
            { label: "Eval", href: "/eval" },
            { label: "Traces" },
            { label: traceId.slice(0, 12) },
            { label: "Reliability Report" },
          ]}
        />
        <div className="p-6">
          <EmptyState
            icon={AlertTriangle}
            title="Report not available"
            description="No scorecard found for this trace. Run an eval first."
          />
        </div>
      </>
    );
  }

  const score = report.overall_score;
  const attribution = report.penalty_attribution;

  const attributionRows: { label: string; key: keyof typeof attribution; color: string }[] = [
    { label: "Agent failures",     key: "agent",            color: "text-red-400" },
    { label: "Dependency issues",  key: "mcp_tool",         color: "text-orange-400" },
    { label: "Prompt injection",   key: "prompt_injection", color: "text-purple-400" },
    { label: "Waste",              key: "waste",            color: "text-amber-400" },
    { label: "User ambiguity",     key: "user_ambiguity",   color: "text-muted-foreground" },
  ];

  const sortedPenalties = [...(report.penalties ?? [])].sort(
    (a, b) => Math.abs(Number(b.amount ?? 0)) - Math.abs(Number(a.amount ?? 0)),
  );

  const dimLabels: { key: keyof typeof report.reliability_dimensions; label: string }[] = [
    { key: "goal_completion",       label: "Goal Completion" },
    { key: "tool_efficiency",       label: "Tool Efficiency" },
    { key: "tool_failures",         label: "Tool Failures" },
    { key: "factual_grounding",     label: "Factual Grounding" },
    { key: "thought_process",       label: "Thought Process" },
    { key: "adversarial_robustness", label: "Adversarial Robustness" },
  ];

  return (
    <>
      <PageHeader
        title="Reliability Report"
        breadcrumbs={[
          { label: "Eval", href: "/eval" },
          { label: "Traces" },
          { label: traceId.slice(0, 12) },
          { label: "Reliability Report" },
        ]}
        actionButtonsRight={
          <div className="flex items-center gap-3">
            <div
              className={`flex items-center gap-2 px-3 py-1.5 rounded border text-sm font-mono ${scoreBg(score)}`}
            >
              <span className={`text-2xl font-bold ${scoreColor(score)}`}>
                {score.toFixed(1)}
              </span>
              <Badge
                variant="outline"
                className={`text-xs ${scoreColor(score)} border-current`}
              >
                {report.overall_grade}
              </Badge>
            </div>
          </div>
        }
      />

      <div className="p-6 space-y-6 max-w-6xl">

        {/* Section 1 — Attribution Summary */}
        <div className="rounded border border-border bg-card overflow-hidden">
          <div className="border-b border-border px-4 py-2.5 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Penalty Attribution
            </span>
            {report.dominant_failure && (
              <span className="text-xs text-muted-foreground">
                Dominant:{" "}
                <span className="font-medium text-foreground">
                  {report.dominant_failure.replace(/_/g, " ")}
                </span>
              </span>
            )}
          </div>
          <table className="w-full text-sm">
            <tbody>
              {attributionRows.map((row) => {
                const val = attribution[row.key];
                const isDominant = report.dominant_failure === row.key;
                return (
                  <tr
                    key={row.key}
                    className={`border-b border-border last:border-0 ${isDominant ? "bg-muted/30" : ""}`}
                  >
                    <td className={`px-4 py-2 ${isDominant ? "font-semibold" : ""}`}>
                      {row.label}
                    </td>
                    <td className={`px-4 py-2 text-right font-mono ${row.color}`}>
                      {val > 0 ? `-${val.toFixed(0)}` : "0"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Section 2 — Causal Trace Timeline */}
        <div className="rounded border border-border bg-card">
          <div className="border-b border-border px-4 py-2.5">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Causal Trace Timeline
            </span>
          </div>
          <div className="p-4">
            {report.causal_timeline.length === 0 ? (
              <p className="text-xs text-muted-foreground">No span data available.</p>
            ) : (
              <div className="space-y-0">
                {report.causal_timeline.map((node, i) => {
                  const style = getStatusStyle(node.status);
                  const isLast = i === report.causal_timeline.length - 1;
                  return (
                    <div key={node.span_id || i} className="flex gap-3">
                      {/* Timeline spine */}
                      <div className="flex flex-col items-center w-5 shrink-0">
                        <div className={`w-3 h-3 rounded-full mt-1 shrink-0 ${style.dot}`} />
                        {!isLast && <div className="w-px flex-1 bg-border mt-0.5" />}
                      </div>
                      {/* Content */}
                      <button
                        className={`flex-1 mb-2 text-left rounded border px-3 py-2 hover:bg-muted/30 transition-colors ${style.border}`}
                        onClick={() => openSpanDrawer(node)}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <Badge
                              variant="outline"
                              className={`text-[10px] px-1.5 py-0 border-current shrink-0 ${style.label}`}
                            >
                              {node.status_label}
                            </Badge>
                            <span className="text-sm truncate">{node.name}</span>
                          </div>
                          <span className="font-mono text-xs text-muted-foreground shrink-0">
                            {fmtLatency(node.latency_ms)}
                          </span>
                        </div>
                        {node.description && (
                          <p className="text-xs text-muted-foreground mt-1 truncate">
                            {node.description}
                          </p>
                        )}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Section 3 — Trace DAG View (collapsible) */}
        <div className="rounded border border-border bg-card">
          <button
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-muted/20 transition-colors"
            onClick={() => setDagOpen((p) => !p)}
          >
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Trace DAG View
            </span>
            {dagOpen ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
          {dagOpen && (
            <div className="border-t border-border p-4">
              <TraceDagSvg
                nodes={report.trace_dag.nodes}
                edges={report.trace_dag.edges}
              />
            </div>
          )}
        </div>

        {/* Section 4 — Penalty Attribution Table */}
        <div className="rounded border border-border bg-card">
          <div className="border-b border-border px-4 py-2.5">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Penalties ({sortedPenalties.length})
            </span>
          </div>
          {sortedPenalties.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={CheckCircle2}
                title="No penalties"
                description="This trace had no scored penalties."
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="h-8 text-xs">Penalty</TableHead>
                    <TableHead className="h-8 text-xs">Dimension</TableHead>
                    <TableHead className="h-8 text-xs">Amount</TableHead>
                    <TableHead className="h-8 text-xs">Severity</TableHead>
                    <TableHead className="h-8 text-xs">Evidence</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedPenalties.map((p, i) => (
                    <TableRow
                      key={i}
                      className="cursor-pointer"
                      onClick={() => openPenaltyDrawer(p)}
                    >
                      <TableCell className="py-1.5 text-xs font-mono">
                        {String(p.event_name ?? "—")}
                      </TableCell>
                      <TableCell className="py-1.5 text-xs text-muted-foreground">
                        {String(p.dimension ?? "—")}
                      </TableCell>
                      <TableCell className="py-1.5 text-xs font-mono text-red-400">
                        -{Math.abs(Number(p.amount ?? 0))}
                      </TableCell>
                      <TableCell className="py-1.5 text-xs">
                        {p.severity ? (
                          <Badge
                            variant="outline"
                            className={`text-[10px] px-1.5 py-0 ${
                              String(p.severity).toLowerCase() === "critical"
                                ? "text-red-400 border-red-400/40"
                                : String(p.severity).toLowerCase() === "major"
                                ? "text-orange-400 border-orange-400/40"
                                : "text-amber-400 border-amber-400/40"
                            }`}
                          >
                            {String(p.severity)}
                          </Badge>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell className="py-1.5 text-xs text-muted-foreground max-w-[200px] truncate">
                        {String(p.evidence ?? "").slice(0, 60)}
                        {String(p.evidence ?? "").length > 60 ? "…" : ""}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>

        {/* Section 6 — Reliability Dimensions */}
        <div className="rounded border border-border bg-card">
          <div className="border-b border-border px-4 py-2.5">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Reliability Dimensions
            </span>
          </div>
          <div className="px-4 py-3 space-y-0.5">
            {dimLabels.map(({ key, label }) => (
              <DimensionBar
                key={key}
                label={label}
                score={report.reliability_dimensions[key] ?? null}
              />
            ))}
          </div>
        </div>

        {/* Section 7 — Waste Hotspots */}
        <div className="rounded border border-border bg-card">
          <div className="border-b border-border px-4 py-2.5">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Waste Hotspots
            </span>
          </div>
          <div className="p-4">
            {report.waste_clusters.length === 0 ? (
              <EmptyState
                icon={Zap}
                title="No waste hotspots detected"
                description="All spans scored clean on waste checks."
              />
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {report.waste_clusters.map((cluster: WasteCluster, i) => (
                  <div
                    key={cluster.cluster_id}
                    className="rounded border border-amber-400/30 bg-amber-400/5 p-3 space-y-2"
                  >
                    <p className="text-xs font-semibold text-amber-400">
                      Cluster #{i + 1} — {fmtCheckType(cluster.check_type)}
                    </p>
                    <p className="font-mono text-[10px] text-muted-foreground break-all">
                      {cluster.span_ids.slice(0, 3).join(" → ")}
                      {cluster.span_ids.length > 3 ? " …" : ""}
                    </p>
                    <div className="flex gap-4 text-xs font-mono">
                      <span>{cluster.tokens_wasted.toLocaleString()} tokens</span>
                      {cluster.cost_usd != null && (
                        <span className="text-amber-400">
                          ${cluster.cost_usd.toFixed(2)}
                        </span>
                      )}
                    </div>
                    {cluster.fix_suggestion && (
                      <p className="text-xs text-muted-foreground">{cluster.fix_suggestion}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Section 8 — Root Cause Analysis */}
        <div className="rounded border border-border bg-card">
          <div className="border-b border-border px-4 py-2.5 flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-muted-foreground" />
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Root Cause Analysis
            </span>
          </div>
          <div className="p-4">
            <RootCauseSection
              scorecardId={report.scorecard_id}
              dominantFailure={report.dominant_failure}
            />
          </div>
        </div>

      </div>

      {/* Section 5 — Evidence Drawer */}
      <EvidenceDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        content={drawerContent}
      />
    </>
  );
}
