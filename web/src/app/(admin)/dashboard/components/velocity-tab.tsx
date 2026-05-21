// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line,
} from "recharts";
import { useExecVelocity, useExecTopAgents, useExecTimeToValue } from "@/hooks/use-api";
import { StatCard } from "./stat-card";

function Sparkline({ data }: { data: number[] }) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const points = data.map((v, i) => `${(i / (data.length - 1)) * 60},${20 - ((v - min) / range) * 18}`).join(" ");

  return (
    <svg width="60" height="20" className="inline-block">
      <polyline
        points={points}
        fill="none"
        stroke="hsl(var(--primary))"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function VelocityTab() {
  const { data: velocity, isLoading: velLoading } = useExecVelocity();
  const { data: topAgents, isLoading: agentsLoading } = useExecTopAgents(10);

  if (velLoading) {
    return (
      <div className="space-y-6 pt-4">
        <div className="h-80 rounded-lg border border-border animate-pulse bg-muted/30" />
      </div>
    );
  }

  return (
    <div className="space-y-6 pt-4">
      {/* KPI Row */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Multiplier" value={`${velocity?.multiplier ?? 0}x`} subtitle="vs baseline" />
        <StatCard label="Current Avg" value={Math.round(velocity?.current_weekly_avg ?? 0)} subtitle="traces/week" />
        <StatCard label="Baseline Avg" value={Math.round(velocity?.baseline_weekly_avg ?? 0)} subtitle="traces/week (first 4 weeks)" />
      </div>

      {/* Velocity Chart */}
      <div className="rounded-lg border border-border p-4">
        <h3 className="text-sm font-medium mb-1">Development Velocity</h3>
        <p className="text-xs text-muted-foreground mb-4">Traces per week over the last 12 weeks</p>
        {velocity?.weekly && velocity.weekly.length > 0 ? (
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={velocity.weekly} margin={{ top: 10, right: 10, bottom: 0, left: -10 }}>
              <defs>
                <linearGradient id="velGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
              <XAxis dataKey="week" className="text-xs" />
              <YAxis className="text-xs" />
              <Tooltip formatter={(value) => [Number(value).toLocaleString(), "Traces"]} />
              <Area type="monotone" dataKey="traces" stroke="hsl(var(--primary))" strokeWidth={2.5} fill="url(#velGrad)" />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-64 flex items-center justify-center text-muted-foreground text-sm">
            Not enough data yet — need at least 4 weeks of traces.
          </div>
        )}
      </div>

      {/* Best Agents Table */}
      <div className="rounded-lg border border-border overflow-hidden">
        <div className="p-4 border-b border-border">
          <h3 className="text-sm font-medium">Best Agents</h3>
          <p className="text-xs text-muted-foreground">Ranked by composite score (sessions × 0.4 + downloads × 0.3 + rating × 0.3)</p>
        </div>
        {agentsLoading ? (
          <div className="p-4">
            <div className="h-40 animate-pulse bg-muted/30 rounded" />
          </div>
        ) : !topAgents || topAgents.length === 0 ? (
          <div className="p-8 text-center text-sm text-muted-foreground">
            No agents with session data yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/30">
                <th className="text-left p-3 font-medium">#</th>
                <th className="text-left p-3 font-medium">Agent</th>
                <th className="text-left p-3 font-medium">Category</th>
                <th className="text-left p-3 font-medium">Score</th>
                <th className="text-left p-3 font-medium">Sessions</th>
                <th className="text-left p-3 font-medium">Downloads</th>
                <th className="text-left p-3 font-medium">Rating</th>
                <th className="text-left p-3 font-medium">Trend</th>
              </tr>
            </thead>
            <tbody>
              {topAgents.map((agent, i) => (
                <tr key={agent.id} className="border-b border-border">
                  <td className="p-3 text-muted-foreground font-mono text-xs">{i + 1}</td>
                  <td className="p-3 font-semibold">{agent.name}</td>
                  <td className="p-3 text-muted-foreground">{agent.category}</td>
                  <td className="p-3 tabular-nums font-semibold">{agent.composite_score}</td>
                  <td className="p-3 tabular-nums">{agent.sessions.toLocaleString()}</td>
                  <td className="p-3 tabular-nums">{agent.downloads.toLocaleString()}</td>
                  <td className="p-3 tabular-nums">{agent.avg_rating ? `${agent.avg_rating}/5` : "—"}</td>
                  <td className="p-3">
                    <Sparkline data={agent.weekly_trend} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Time to Value */}
      <TimeToValue />
    </div>
  );
}

function TimeToValue() {
  const { data, isLoading } = useExecTimeToValue();

  if (isLoading) {
    return <div className="h-40 rounded-lg border border-border animate-pulse bg-muted/30" />;
  }

  if (!data || data.agents.length === 0) return null;

  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">Time to Value</h3>
          <p className="text-xs text-muted-foreground">Days from deployment to reaching 100 sessions</p>
        </div>
        {data.avg_days_to_100 !== null && (
          <div className="text-right">
            <p className="text-lg font-bold tabular-nums">{data.avg_days_to_100} days</p>
            <p className="text-[11px] text-muted-foreground">avg time to 100 sessions</p>
          </div>
        )}
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/30">
            <th className="text-left p-3 font-medium">Agent</th>
            <th className="text-left p-3 font-medium">Category</th>
            <th className="text-left p-3 font-medium">Deployed</th>
            <th className="text-left p-3 font-medium">Days to 100</th>
            <th className="text-left p-3 font-medium">Sessions</th>
          </tr>
        </thead>
        <tbody>
          {data.agents.slice(0, 10).map((agent) => (
            <tr key={agent.id} className="border-b border-border last:border-0">
              <td className="p-3 font-medium">{agent.name}</td>
              <td className="p-3 text-muted-foreground">{agent.category}</td>
              <td className="p-3 tabular-nums text-xs text-muted-foreground">{agent.created_at}</td>
              <td className="p-3 tabular-nums">
                {agent.days_to_100 !== null ? (
                  <span className={agent.days_to_100 <= 7 ? "text-green-600 font-semibold" : agent.days_to_100 <= 30 ? "text-foreground" : "text-orange-500"}>
                    {agent.days_to_100}d
                  </span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </td>
              <td className="p-3 tabular-nums">{agent.current_sessions.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
