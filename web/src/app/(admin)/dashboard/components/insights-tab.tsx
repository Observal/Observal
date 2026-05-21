// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useState } from "react";
import Link from "next/link";
import { useExecStrategicInsights, useExecDeveloperBreakdown, useExecInactivityAlerts, useRegistryList, useInsightReports, useGenerateInsight } from "@/hooks/use-api";
import type { RegistryItem, InsightReportListItem } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { StatCard } from "./stat-card";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { AlertTriangle, TrendingUp, Zap, Users, Cpu, FileText, Loader2, Sparkles, Crown } from "lucide-react";

const effortColors: Record<string, { bg: string; text: string; label: string }> = {
  low: { bg: "bg-emerald-500/10", text: "text-emerald-500", label: "Quick Win" },
  medium: { bg: "bg-amber-500/10", text: "text-amber-500", label: "Medium Effort" },
  high: { bg: "bg-red-500/10", text: "text-red-500", label: "High Effort" },
};

function formatCurrency(value: number): string {
  if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
  return `$${value.toFixed(0)}`;
}

function StrategicInsights() {
  const { data: insights, isLoading } = useExecStrategicInsights();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 rounded-lg border border-border animate-pulse bg-muted/30" />
          ))}
        </div>
        <div className="h-64 rounded-lg border border-border animate-pulse bg-muted/30" />
      </div>
    );
  }

  if (!insights || (insights.total_active_users === 0 && insights.quick_wins.length === 0)) {
    return (
      <div className="rounded-md border border-border p-8 text-center text-muted-foreground">
        <Cpu className="h-8 w-8 mx-auto mb-3 opacity-50" />
        <p className="text-sm font-medium mb-1">No telemetry data yet</p>
        <p className="text-xs">Strategic insights will appear once sessions are recorded.</p>
      </div>
    );
  }

  const totalQuickWinSavings = insights.quick_wins.reduce((s, w) => s + w.estimated_savings, 0);

  return (
    <div className="space-y-6">
      {/* KPI Row */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Active Users" value={insights.total_active_users} subtitle="last 30 days" />
        <StatCard
          label="Power Users Drive"
          value={`${insights.power_user_value_pct}%`}
          subtitle={`of value (top ${insights.power_user_pct}%)`}
        />
        <StatCard label="Automatable Tasks" value={`${insights.automatable_pct}%`} subtitle="could run fully autonomous" />
        <StatCard
          label="Quick Win Savings"
          value={formatCurrency(totalQuickWinSavings)}
          subtitle="recoverable/month"
        />
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
            Combined potential: {formatCurrency(totalQuickWinSavings)}/month
          </p>
          <div className="space-y-3">
            {insights.quick_wins.map((win, i) => {
              const effort = effortColors[win.effort] ?? effortColors.medium;
              return (
                <div key={i} className="rounded-md border border-border p-4">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-medium">{win.title}</h4>
                    <span className={`text-[10px] px-2 py-0.5 rounded ${effort.bg} ${effort.text} font-semibold`}>
                      {effort.label} · {formatCurrency(win.estimated_savings)}/mo
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed">{win.detail}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Department Gaps */}
      {insights.department_gaps.length > 0 && (
        <div className="rounded-lg border border-border p-5">
          <div className="flex items-center gap-2 mb-1">
            <AlertTriangle className="h-4 w-4 text-rose-400" />
            <span className="text-[11px] font-semibold uppercase tracking-wide text-rose-400">Adoption Gaps</span>
          </div>
          <h3 className="text-sm font-semibold mb-4">Departments with low AI adoption</h3>
          <div className="space-y-3">
            {insights.department_gaps.filter(d => d.adoption_pct < 80).map((dept) => (
              <div key={dept.department} className="flex items-center gap-4">
                <span className="text-sm w-32 truncate font-medium">{dept.department}</span>
                <div className="flex-1 h-2 rounded-full bg-muted/30 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-rose-500 to-amber-400"
                    style={{ width: `${dept.adoption_pct}%` }}
                  />
                </div>
                <span className="text-xs font-semibold tabular-nums w-10 text-right">{dept.adoption_pct}%</span>
                <span className="text-xs text-muted-foreground w-64 truncate">{dept.opportunity}</span>
              </div>
            ))}
            {insights.department_gaps.filter(d => d.adoption_pct < 80).length === 0 && (
              <p className="text-xs text-muted-foreground">All departments are above 80% adoption.</p>
            )}
          </div>
        </div>
      )}

      {/* Model Comparison */}
      {insights.model_comparison.length > 0 && (
        <div className="rounded-lg border border-border p-5">
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp className="h-4 w-4 text-cyan-400" />
            <span className="text-[11px] font-semibold uppercase tracking-wide text-cyan-400">Model Provider</span>
          </div>
          <h3 className="text-sm font-semibold mb-4">Cost and performance by model</h3>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={insights.model_comparison.slice(0, 6)} margin={{ top: 5, right: 5, bottom: 5, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
                <XAxis dataKey="model" className="text-[10px]" tick={{ fontSize: 10 }} interval={0} angle={-20} textAnchor="end" height={50} />
                <YAxis className="text-xs" tickFormatter={(v) => `$${v}`} />
                <Tooltip formatter={(value) => [`$${Number(value).toFixed(4)}`, "Avg Cost"]} />
                <Bar dataKey="avg_cost" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>

            <div className="space-y-2">
              {insights.model_comparison.slice(0, 5).map((m) => (
                <div key={m.model} className="flex items-center justify-between p-3 rounded-md border border-border">
                  <div>
                    <p className="text-sm font-medium">{m.model}</p>
                    <p className="text-[11px] text-muted-foreground">{m.best_at}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-semibold text-emerald-500">${m.avg_cost.toFixed(4)}</p>
                    <p className="text-[11px] text-muted-foreground">{m.success_rate}% success · {m.sessions} sessions</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Platform Comparison */}
      {insights.platform_comparison.length > 0 && (
        <div className="rounded-lg border border-border p-5">
          <div className="flex items-center gap-2 mb-1">
            <Users className="h-4 w-4 text-violet-400" />
            <span className="text-[11px] font-semibold uppercase tracking-wide text-violet-400">IDE Performance</span>
          </div>
          <h3 className="text-sm font-semibold mb-4">Task completion speed by platform</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {insights.platform_comparison.map((p) => (
              <div key={p.platform} className="rounded-md border border-border p-4 text-center">
                <p className="text-sm font-semibold mb-1">{p.platform}</p>
                <p className="text-lg font-bold text-foreground">
                  {p.avg_task_time_ms > 60000
                    ? `${(p.avg_task_time_ms / 60000).toFixed(1)}m`
                    : `${(p.avg_task_time_ms / 1000).toFixed(1)}s`}
                </p>
                <p className="text-[11px] text-muted-foreground">avg task time</p>
                <div className="flex justify-center gap-3 mt-2 text-[11px]">
                  <span>{p.sessions} sessions</span>
                  <span className="text-emerald-500">{p.success_rate}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Automatable Work */}
      {insights.automatable_pct > 0 && (
        <div className="rounded-lg border border-dashed border-amber-500/30 bg-amber-500/5 p-5">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-500">Automation Opportunity</span>
          </div>
          <h3 className="text-sm font-semibold mb-1">
            {insights.automatable_pct}% of tasks could run fully autonomous
          </h3>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Sessions with fewer than 3,000 tokens and 5 or fewer events are likely routine tasks
            (dependency bumps, config changes, simple fixes) that could run with approval gates only,
            freeing engineering time for architecture and product work.
          </p>
        </div>
      )}

      {/* Developer Breakdown */}
      <DeveloperBreakdown />

      {/* Inactivity Alerts */}
      <InactivityAlerts />
    </div>
  );
}

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
                <td className="p-2.5 tabular-nums text-xs">{(dev.tokens_consumed / 1000).toFixed(0)}K</td>
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

function InactivityAlerts() {
  const { data, isLoading } = useExecInactivityAlerts();

  if (isLoading) {
    return <div className="h-32 rounded-lg border border-border animate-pulse bg-muted/30" />;
  }

  const agents = data?.inactive_agents ?? [];
  const users = data?.inactive_users ?? [];

  if (agents.length === 0 && users.length === 0) return null;

  return (
    <div className="rounded-lg border border-border p-5">
      <div className="flex items-center gap-2 mb-1">
        <AlertTriangle className="h-4 w-4 text-orange-400" />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-orange-400">Churn Risk</span>
      </div>
      <h3 className="text-sm font-semibold mb-4">
        Recently inactive — were active 2-4 weeks ago, silent in last 14 days
      </h3>

      {agents.length > 0 && (
        <div className="mb-4">
          <p className="text-xs font-medium text-muted-foreground mb-2">Agents ({agents.length})</p>
          <div className="space-y-1.5">
            {agents.map((a) => (
              <div key={a.id} className="flex items-center justify-between text-sm p-2 rounded-md bg-muted/20">
                <div>
                  <span className="font-medium">{a.name}</span>
                  <span className="text-xs text-muted-foreground ml-2">{a.category}</span>
                </div>
                <span className="text-xs text-muted-foreground">{a.previous_sessions} sessions before going silent</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {users.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2">Users ({users.length})</p>
          <div className="space-y-1.5">
            {users.map((u) => (
              <div key={u.user_id} className="flex items-center justify-between text-sm p-2 rounded-md bg-muted/20">
                <div>
                  <span className="font-medium">{u.name}</span>
                  <span className="text-xs text-muted-foreground ml-2">{u.department}</span>
                </div>
                <span className="text-xs text-muted-foreground">{u.previous_sessions} sessions before going silent</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AgentReports() {
  const { data: agents, isLoading: agentsLoading } = useRegistryList("agents");
  const [selectedAgentId, setSelectedAgentId] = useState<string | undefined>(undefined);
  const { data: reports, isLoading: reportsLoading } = useInsightReports(selectedAgentId);
  const generateInsight = useGenerateInsight();

  if (agentsLoading) {
    return <div className="h-40 rounded-lg border border-border animate-pulse bg-muted/30" />;
  }

  const agentList = (agents ?? []) as RegistryItem[];

  if (agentList.length === 0) {
    return (
      <div className="rounded-md border border-border p-8 text-center text-muted-foreground">
        <FileText className="h-8 w-8 mx-auto mb-3 opacity-50" />
        <p className="text-sm font-medium mb-1">No agents available</p>
        <p className="text-xs">Deploy agents to the registry to generate insight reports.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border p-4">
        <h3 className="text-sm font-medium mb-3">Per-Agent Reports</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
          {agentList.slice(0, 12).map((agent) => (
            <button
              key={agent.id}
              onClick={() => setSelectedAgentId(agent.id)}
              className={`text-left p-3 rounded-md border text-sm transition-colors ${
                selectedAgentId === agent.id
                  ? "border-primary bg-primary/5 font-medium"
                  : "border-border hover:bg-muted/30"
              }`}
            >
              <span className="truncate block">{agent.name}</span>
              <span className="text-xs text-muted-foreground">{String(agent.version ?? "")}</span>
            </button>
          ))}
        </div>
      </div>

      {selectedAgentId && (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="p-4 border-b border-border flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium">Insight Reports</h3>
              <p className="text-xs text-muted-foreground">
                {agentList.find((a) => a.id === selectedAgentId)?.name ?? ""}
              </p>
            </div>
            <button
              onClick={() => generateInsight.mutate({ agentId: selectedAgentId })}
              disabled={generateInsight.isPending}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {generateInsight.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Sparkles className="h-3 w-3" />
              )}
              Generate Report
            </button>
          </div>

          {reportsLoading ? (
            <div className="p-6">
              <div className="h-24 animate-pulse bg-muted/30 rounded" />
            </div>
          ) : !reports || reports.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              <p className="mb-2">No insight reports for this agent yet.</p>
              <p className="text-xs">Click &quot;Generate Report&quot; to analyze this agent&apos;s recent sessions.</p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {(reports as InsightReportListItem[]).slice(0, 5).map((report) => (
                <Link
                  key={report.id}
                  href={`/insights/${report.id}`}
                  className="flex items-center justify-between p-4 hover:bg-muted/20 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    <div>
                      <div className="text-sm font-medium">
                        {new Date(report.period_start).toLocaleDateString()} — {new Date(report.period_end).toLocaleDateString()}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {report.sessions_analyzed} sessions analyzed
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge
                      variant={
                        (report.status === "completed" ? "default" : report.status === "failed" ? "destructive" : "secondary") as "default" | "secondary" | "destructive"
                      }
                      className="text-[10px]"
                    >
                      {report.status === "running" && <Loader2 className="h-2.5 w-2.5 animate-spin mr-1" />}
                      {report.status}
                    </Badge>
                    {report.completed_at && (
                      <span className="text-xs text-muted-foreground">
                        {new Date(report.completed_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function InsightsTab() {
  const [view, setView] = useState<"strategic" | "agents">("strategic");

  return (
    <div className="space-y-6 pt-4">
      {/* View Toggle */}
      <div className="flex items-center gap-1 p-1 rounded-lg bg-muted/30 w-fit">
        <button
          onClick={() => setView("strategic")}
          className={`px-4 py-1.5 rounded-md text-xs font-medium transition-colors ${
            view === "strategic" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Strategic Insights
        </button>
        <button
          onClick={() => setView("agents")}
          className={`px-4 py-1.5 rounded-md text-xs font-medium transition-colors ${
            view === "agents" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Per-Agent Reports
        </button>
      </div>

      {view === "strategic" ? <StrategicInsights /> : <AgentReports />}
    </div>
  );
}
