// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useExecAIInsights, useExecDeveloperBreakdown } from "@/hooks/use-api";
import { Zap, AlertTriangle, TrendingUp, Users, Cpu, Crown, Loader2 } from "lucide-react";

const effortColors: Record<string, { bg: string; text: string; label: string }> = {
  low: { bg: "bg-emerald-500/10", text: "text-emerald-500", label: "Quick Win" },
  medium: { bg: "bg-amber-500/10", text: "text-amber-500", label: "Medium Effort" },
  high: { bg: "bg-red-500/10", text: "text-red-500", label: "High Effort" },
};

function DeveloperBreakdown() {
  const { data, isLoading } = useExecDeveloperBreakdown(20);

  if (isLoading) {
    return <div className="h-48 rounded-lg border border-border animate-pulse bg-muted/30" />;
  }

  if (!data || data.active_developers === 0) return null;

  return (
    <div className="rounded-lg border border-border p-5">
      <div className="flex items-center gap-2 mb-1">
        <Crown className="h-4 w-4 text-amber-400" />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-400">Developer Activity</span>
      </div>
      <h3 className="text-sm font-semibold mb-1">
        {data.active_developers} active developers — top 20% drive {data.top_20_value_pct}% of value
      </h3>
      <p className="text-xs text-muted-foreground mb-4">
        {data.total_developers} total developers in org, {data.active_developers} active in the last 30 days.
      </p>

      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/30">
              <th className="text-left p-2.5 font-medium text-xs">#</th>
              <th className="text-left p-2.5 font-medium text-xs">Developer</th>
              <th className="text-left p-2.5 font-medium text-xs">Department</th>
              <th className="text-left p-2.5 font-medium text-xs">Sessions</th>
              <th className="text-left p-2.5 font-medium text-xs">Tokens</th>
              <th className="text-left p-2.5 font-medium text-xs">Cost</th>
              <th className="text-left p-2.5 font-medium text-xs">Percentile</th>
            </tr>
          </thead>
          <tbody>
            {data.developers.map((dev, i) => (
              <tr key={dev.user_id} className="border-b border-border last:border-0">
                <td className="p-2.5 text-muted-foreground font-mono text-xs">{i + 1}</td>
                <td className="p-2.5 font-medium">{dev.name}</td>
                <td className="p-2.5 text-muted-foreground">{dev.department}</td>
                <td className="p-2.5 tabular-nums">{dev.sessions.toLocaleString()}</td>
                <td className="p-2.5 tabular-nums text-xs">{dev.tokens_consumed >= 1000000 ? `${(dev.tokens_consumed / 1000000).toFixed(1)}M` : `${(dev.tokens_consumed / 1000).toFixed(0)}K`}</td>
                <td className="p-2.5 tabular-nums text-xs font-mono">${dev.cost.toFixed(3)}</td>
                <td className="p-2.5">
                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                    dev.percentile >= 80 ? "bg-emerald-500/10 text-emerald-500" :
                    dev.percentile >= 50 ? "bg-blue-500/10 text-blue-500" :
                    "bg-muted text-muted-foreground"
                  }`}>
                    Top {100 - dev.percentile}%
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function InsightsTab() {
  const { data: insights, isLoading } = useExecAIInsights();

  if (isLoading) {
    return (
      <div className="space-y-6 pt-4">
        <div className="rounded-lg border border-border p-8 flex flex-col items-center justify-center text-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground mb-3" />
          <p className="text-sm font-medium">Generating AI Insights...</p>
          <p className="text-xs text-muted-foreground mt-1">Analyzing your organization&apos;s telemetry data</p>
        </div>
      </div>
    );
  }

  if (!insights || !insights.generated) {
    return (
      <div className="space-y-6 pt-4">
        <div className="rounded-md border border-border p-8 text-center text-muted-foreground">
          <Cpu className="h-8 w-8 mx-auto mb-3 opacity-50" />
          <p className="text-sm font-medium mb-1">AI Insights not available</p>
          <p className="text-xs">Configure insights models in Settings to enable LLM-powered strategic recommendations.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 pt-4">
      {/* Header */}
      <div className="rounded-lg border border-border p-5">
        <div className="flex items-center gap-3">
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-400" />
          <h2 className="text-base font-semibold">AI Insights</h2>
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          Strategic recommendations based on usage patterns across your organization. Updated on each refresh.
        </p>
      </div>

      {/* Quick Wins */}
      {insights.quick_wins.length > 0 && (
        <div className="rounded-lg border border-border p-5">
          <div className="flex items-center gap-2 mb-1">
            <Zap className="h-4 w-4 text-emerald-500" />
            <span className="text-[11px] font-semibold uppercase tracking-wide text-emerald-500">Quick Wins</span>
          </div>
          <h3 className="text-sm font-semibold mb-1">Immediate savings with minimal effort</h3>
          <p className="text-xs text-muted-foreground mb-4">
            Combined potential: {insights.quick_wins.map(w => w.estimated_savings).join(" + ")} saved
          </p>
          <div className="space-y-3">
            {insights.quick_wins.map((win, i) => {
              const effort = effortColors[win.effort] ?? effortColors.medium;
              return (
                <div key={i} className="rounded-md border border-border p-4">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-medium">{win.title}</h4>
                    <span className={`text-[10px] px-2 py-0.5 rounded ${effort.bg} ${effort.text} font-semibold`}>
                      {effort.label} · {win.estimated_savings}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed">{win.detail}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Adoption Gaps */}
      {insights.adoption_gaps.length > 0 && (
        <div className="rounded-lg border border-border p-5">
          <div className="flex items-center gap-2 mb-1">
            <AlertTriangle className="h-4 w-4 text-rose-400" />
            <span className="text-[11px] font-semibold uppercase tracking-wide text-rose-400">Adoption Gaps</span>
            <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-500 font-semibold">High Impact</span>
          </div>
          <div className="space-y-4 mt-3">
            {insights.adoption_gaps.map((gap, i) => (
              <div key={i}>
                <h4 className="text-sm font-semibold mb-1">{gap.title}</h4>
                <p className="text-sm text-muted-foreground leading-relaxed">{gap.detail}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Platform Insight */}
      {insights.platform_insight.title && insights.platform_insight.title !== "Insufficient data" && (
        <div className="rounded-lg border border-border p-5">
          <div className="flex items-center gap-2 mb-1">
            <Users className="h-4 w-4 text-violet-400" />
            <span className="text-[11px] font-semibold uppercase tracking-wide text-violet-400">IDE Performance</span>
            <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-500 font-semibold">High Impact</span>
          </div>
          <h4 className="text-sm font-semibold mt-2 mb-1">{insights.platform_insight.title}</h4>
          <p className="text-sm text-muted-foreground leading-relaxed">{insights.platform_insight.detail}</p>
        </div>
      )}

      {/* Automation Opportunity */}
      {insights.automation_opportunity.title && insights.automation_opportunity.title !== "Insufficient data" && (
        <div className="rounded-lg border border-dashed border-amber-500/30 bg-amber-500/5 p-5">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-500">Automation Opportunity</span>
          </div>
          <h4 className="text-sm font-semibold mb-1">{insights.automation_opportunity.title}</h4>
          <p className="text-sm text-muted-foreground leading-relaxed">{insights.automation_opportunity.detail}</p>
        </div>
      )}

      {/* Model Insight */}
      {insights.model_insight.title && insights.model_insight.title !== "Insufficient data" && (
        <div className="rounded-lg border border-border p-5">
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp className="h-4 w-4 text-cyan-400" />
            <span className="text-[11px] font-semibold uppercase tracking-wide text-cyan-400">Model Provider</span>
            <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-500 font-semibold">High Impact</span>
          </div>
          <h4 className="text-sm font-semibold mt-2 mb-1">{insights.model_insight.title}</h4>
          <p className="text-sm text-muted-foreground leading-relaxed">{insights.model_insight.detail}</p>
        </div>
      )}

      {/* Usage Pattern */}
      {insights.usage_pattern.title && insights.usage_pattern.title !== "Insufficient data" && (
        <div className="rounded-lg border border-border p-5">
          <div className="flex items-center gap-2 mb-1">
            <Crown className="h-4 w-4 text-amber-400" />
            <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-400">Usage Pattern</span>
          </div>
          <h4 className="text-sm font-semibold mt-2 mb-1">{insights.usage_pattern.title}</h4>
          <p className="text-sm text-muted-foreground leading-relaxed">{insights.usage_pattern.detail}</p>
        </div>
      )}

      {/* Developer Breakdown */}
      <DeveloperBreakdown />
    </div>
  );
}
