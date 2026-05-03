"use client";

import { use } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Lightbulb,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  Zap,
  Users,
  Timer,
  AlertTriangle,
  Wrench,
  TrendingUp,
  DollarSign,
  Database,
} from "lucide-react";
import { useInsightReport } from "@/hooks/use-api";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layouts/page-header";
import { ErrorState } from "@/components/shared/error-state";
import type { InsightReport } from "@/lib/types";

function StatusIndicator({ status }: { status: InsightReport["status"] }) {
  switch (status) {
    case "completed":
      return (
        <div className="inline-flex items-center gap-1.5 text-sm font-medium text-success">
          <CheckCircle2 className="h-4 w-4" /> Completed
        </div>
      );
    case "running":
      return (
        <div className="inline-flex items-center gap-1.5 text-sm font-medium text-info">
          <Loader2 className="h-4 w-4 animate-spin" /> Generating report...
        </div>
      );
    case "pending":
      return (
        <div className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
          <Clock className="h-4 w-4" /> Queued
        </div>
      );
    case "failed":
      return (
        <div className="inline-flex items-center gap-1.5 text-sm font-medium text-destructive">
          <XCircle className="h-4 w-4" /> Failed
        </div>
      );
  }
}

function MetricCard({
  label,
  value,
  icon: Icon,
  subtext,
}: {
  label: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
  subtext?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-muted-foreground mb-1">
        <Icon className="h-4 w-4" />
        <span className="text-xs font-medium uppercase tracking-wider">{label}</span>
      </div>
      <div className="font-[family-name:var(--font-mono)] text-2xl font-bold tabular-nums">
        {value}
      </div>
      {subtext && (
        <div className="text-xs text-muted-foreground mt-1">{subtext}</div>
      )}
    </div>
  );
}

function NarrativeSection({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center gap-2 px-5 py-3 border-b border-border">
        <Icon className="h-4 w-4 text-primary-accent" />
        <h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">{title}</h3>
      </div>
      <div className="px-5 py-4">{children}</div>
    </div>
  );
}

function ToolsTable({ tools }: { tools: { name: string; invocations: string; errors: string }[] | undefined }) {
  if (!tools || tools.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="flex items-center gap-2 px-5 py-3 border-b border-border">
        <Wrench className="h-4 w-4 text-primary-accent" />
        <h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">Top Tools</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-xs text-muted-foreground uppercase tracking-wider">
              <th className="text-left px-5 py-2 font-medium">Tool</th>
              <th className="text-right px-5 py-2 font-medium">Calls</th>
              <th className="text-right px-5 py-2 font-medium">Errors</th>
              <th className="text-right px-5 py-2 font-medium">Error Rate</th>
            </tr>
          </thead>
          <tbody>
            {tools.slice(0, 10).map((tool) => {
              const invocations = Number(tool.invocations) || 0;
              const errors = Number(tool.errors) || 0;
              const toolErrorRate = invocations > 0 ? ((errors / invocations) * 100).toFixed(1) : "0.0";

              return (
                <tr key={tool.name} className="border-b border-border last:border-0 hover:bg-muted/30">
                  <td className="px-5 py-2.5 font-[family-name:var(--font-mono)] text-xs">{tool.name}</td>
                  <td className="px-5 py-2.5 text-right tabular-nums">{invocations.toLocaleString()}</td>
                  <td className="px-5 py-2.5 text-right tabular-nums">{errors}</td>
                  <td className="px-5 py-2.5 text-right tabular-nums">
                    <span className={Number(toolErrorRate) > 10 ? "text-destructive font-medium" : ""}>
                      {toolErrorRate}%
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CostSection({ cost }: { cost: NonNullable<InsightReport["metrics"]>["cost"] }) {
  if (!cost || cost.total_cost_usd === 0) return null;

  const formatCost = (n: number) => {
    if (n >= 1) return `$${n.toFixed(2)}`;
    if (n >= 0.01) return `$${n.toFixed(3)}`;
    return `$${n.toFixed(4)}`;
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard label="Total Cost" value={formatCost(cost.total_cost_usd)} icon={DollarSign} />
        <MetricCard label="Cost / Session" value={formatCost(cost.avg_cost_per_session)} icon={DollarSign} />
        <MetricCard
          label="Cache Efficiency"
          value={`${(cost.cache_efficiency_ratio * 100).toFixed(0)}%`}
          icon={Database}
          subtext="tokens from cache"
        />
        <MetricCard
          label="P90 Session"
          value={formatCost(cost.p90_session_cost)}
          icon={DollarSign}
          subtext={`P50: ${formatCost(cost.p50_session_cost)}`}
        />
      </div>

      {cost.cost_by_model.length > 1 && (
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="flex items-center gap-2 px-5 py-3 border-b border-border">
            <DollarSign className="h-4 w-4 text-primary-accent" />
            <h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">Cost by Model</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground uppercase tracking-wider">
                  <th className="text-left px-5 py-2 font-medium">Model</th>
                  <th className="text-right px-5 py-2 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {cost.cost_by_model.map((row) => (
                  <tr key={row.model} className="border-b border-border last:border-0 hover:bg-muted/30">
                    <td className="px-5 py-2.5 font-[family-name:var(--font-mono)] text-xs">{row.model}</td>
                    <td className="px-5 py-2.5 text-right tabular-nums">{formatCost(row.total_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function ErrorCategories({ toolErrors }: { toolErrors: NonNullable<InsightReport["metrics"]>["tool_errors"] }) {
  if (!toolErrors || toolErrors.total_categorized === 0) return null;

  const categories = Object.entries(toolErrors.categories).sort(([, a], [, b]) => b - a);
  const labelMap: Record<string, string> = {
    command_failed: "Command Failed",
    user_rejected: "User Rejected",
    edit_failed: "Edit Failed",
    file_changed: "File Changed",
    file_too_large: "File Too Large",
    file_not_found: "File Not Found",
    timeout: "Timeout",
    permission_denied: "Permission Denied",
    other: "Other",
  };

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="flex items-center gap-2 px-5 py-3 border-b border-border">
        <AlertTriangle className="h-4 w-4 text-primary-accent" />
        <h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
          Error Categories ({toolErrors.total_categorized} total)
        </h3>
      </div>
      <div className="px-5 py-4 space-y-2">
        {categories.map(([cat, count]) => {
          const pct = ((count / toolErrors.total_categorized) * 100).toFixed(0);
          return (
            <div key={cat} className="flex items-center gap-3 text-sm">
              <span className="w-32 truncate text-muted-foreground">{labelMap[cat] ?? cat}</span>
              <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-destructive/60 rounded-full"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="w-12 text-right tabular-nums text-xs">{count} ({pct}%)</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ReportContent({ report }: { report: InsightReport }) {
  const metrics = report.metrics;
  const narrative = report.narrative;

  const totalSessions = Number(metrics?.overview?.total_sessions) || 0;
  const uniqueUsers = Number(metrics?.overview?.unique_users) || 0;
  const totalTokens = Number(metrics?.tokens?.total_tokens) || 0;
  const cacheRead = Number(metrics?.tokens?.total_cache_read_tokens) || 0;
  const cacheWrite = Number(metrics?.tokens?.total_cache_write_tokens) || 0;
  const avgDuration = Number(metrics?.duration?.avg_duration_seconds) || 0;
  const toolCalls = Number(metrics?.errors?.total_tool_calls) || 0;

  const formatTokens = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return n.toString();
  };

  const formatDuration = (seconds: number) => {
    if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`;
    if (seconds >= 60) return `${(seconds / 60).toFixed(0)}m`;
    return `${seconds.toFixed(0)}s`;
  };

  return (
    <div className="space-y-6">
      {/* At a Glance */}
      {narrative?.at_a_glance && (
        <div className="rounded-lg border border-primary-accent/20 bg-primary-accent/5 p-5">
          <div className="flex items-center gap-2 mb-2">
            <Lightbulb className="h-4 w-4 text-primary-accent" />
            <h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">At a Glance</h3>
          </div>
          <p className="text-sm leading-relaxed">{narrative.at_a_glance}</p>
        </div>
      )}

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricCard label="Sessions" value={totalSessions} icon={Zap} />
        <MetricCard label="Users" value={uniqueUsers} icon={Users} />
        <MetricCard label="Tokens" value={formatTokens(totalTokens)} icon={TrendingUp} />
        <MetricCard
          label="Cache Read"
          value={formatTokens(cacheRead)}
          icon={Database}
          subtext={cacheWrite > 0 ? `${formatTokens(cacheWrite)} write` : undefined}
        />
        <MetricCard
          label="Tool Calls"
          value={toolCalls}
          icon={Wrench}
        />
        <MetricCard
          label="Avg Duration"
          value={formatDuration(avgDuration)}
          icon={Timer}
        />
      </div>

      {/* Cost Section */}
      <CostSection cost={metrics?.cost} />

      {/* Tools Table */}
      <ToolsTable tools={metrics?.tools} />

      {/* Error Categories */}
      <ErrorCategories toolErrors={metrics?.tool_errors} />

      {/* Narrative Sections */}
      {narrative?.usage_patterns && narrative.usage_patterns.length > 0 && (
        <NarrativeSection title="Usage Patterns" icon={TrendingUp}>
          <ul className="space-y-2">
            {narrative.usage_patterns.map((item, i) => (
              <li key={i} className="flex gap-2 text-sm">
                <span className="text-muted-foreground mt-0.5 shrink-0">-</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </NarrativeSection>
      )}

      {narrative?.friction_analysis && narrative.friction_analysis.length > 0 && (
        <NarrativeSection title="Friction Analysis" icon={AlertTriangle}>
          <ul className="space-y-2">
            {narrative.friction_analysis.map((item, i) => (
              <li key={i} className="flex gap-2 text-sm">
                <span className="text-destructive mt-0.5 shrink-0">-</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </NarrativeSection>
      )}

      {narrative?.suggestions && narrative.suggestions.length > 0 && (
        <NarrativeSection title="Suggestions" icon={Lightbulb}>
          <ul className="space-y-2">
            {narrative.suggestions.map((item, i) => (
              <li key={i} className="flex gap-2 text-sm">
                <span className="text-primary-accent font-semibold mt-0.5 shrink-0">{i + 1}.</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </NarrativeSection>
      )}

      {/* No narrative fallback */}
      {!narrative && metrics && (
        <div className="rounded-lg border border-border bg-muted/30 p-5 text-center">
          <p className="text-sm text-muted-foreground">
            Narrative analysis unavailable. Configure an eval model to enable LLM-powered insights.
          </p>
        </div>
      )}
    </div>
  );
}

export default function InsightReportPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = use(params);
  const { data: report, isLoading, isError } = useInsightReport(reportId);

  return (
    <>
      <PageHeader
        title="Insight Report"
        actionButtonsRight={
          <Link href="/insights">
            <Button variant="ghost" size="sm" className="gap-1.5">
              <ArrowLeft className="h-4 w-4" /> Back
            </Button>
          </Link>
        }
      />

      <div className="p-4 sm:p-6 max-w-5xl">
        {isLoading && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {isError && <ErrorState message="Failed to load report" />}

        {report && (
          <div className="space-y-6">
            {/* Header with status and metadata */}
            <div className="flex items-center justify-between">
              <StatusIndicator status={report.status} />
              <div className="text-xs text-muted-foreground space-x-3">
                <span>
                  {new Date(report.period_start).toLocaleDateString()} - {new Date(report.period_end).toLocaleDateString()}
                </span>
                {report.sessions_analyzed > 0 && (
                  <span>{report.sessions_analyzed} sessions analyzed</span>
                )}
              </div>
            </div>

            {/* Loading state */}
            {(report.status === "pending" || report.status === "running") && (
              <div className="flex flex-col items-center justify-center py-16 gap-3">
                <Loader2 className="h-8 w-8 animate-spin text-primary-accent" />
                <p className="text-sm text-muted-foreground">
                  {report.status === "pending" ? "Waiting in queue..." : "Computing metrics and generating analysis..."}
                </p>
              </div>
            )}

            {/* Error state */}
            {report.status === "failed" && (
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-5">
                <p className="text-sm font-medium text-destructive">Report generation failed</p>
                {report.error_message && (
                  <p className="text-xs text-muted-foreground mt-1 font-[family-name:var(--font-mono)]">
                    {report.error_message}
                  </p>
                )}
              </div>
            )}

            {/* Completed: show content */}
            {report.status === "completed" && <ReportContent report={report} />}
          </div>
        )}
      </div>
    </>
  );
}
