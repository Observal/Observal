// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
} from "recharts";
import { useExecPlatforms, useExecStrategicInsights } from "@/hooks/use-api";
import type { ExecPlatformScore } from "@/lib/types";

const COLORS = ["#2563eb", "#7c3aed", "#0d9488", "#f59e0b", "#e11d48", "#6366f1", "#84cc16"];

function deriveRadarData(p: ExecPlatformScore, best: { latency: number; cost: number }) {
  const successScore = p.success_rate;
  const speedScore = best.latency > 0 ? Math.max(0, 100 - ((p.avg_latency_ms / best.latency) - 1) * 50) : 100;
  const costScore = best.cost > 0 ? Math.max(0, 100 - ((p.avg_cost / best.cost) - 1) * 50) : 100;
  const reliabilityScore = 100 - p.error_rate;
  const volumeScore = p.composite_score;

  return [
    { metric: "Success Rate", value: Math.min(successScore, 100) },
    { metric: "Speed", value: Math.min(Math.max(speedScore, 0), 100) },
    { metric: "Cost Efficiency", value: Math.min(Math.max(costScore, 0), 100) },
    { metric: "Reliability", value: Math.min(Math.max(reliabilityScore, 0), 100) },
    { metric: "Volume", value: Math.min(Math.max(volumeScore, 0), 100) },
  ];
}

export function InvestmentsTab() {
  const { data: platforms, isLoading } = useExecPlatforms();
  const [selected, setSelected] = useState(0);

  if (isLoading) {
    return (
      <div className="space-y-6 pt-4">
        <div className="h-80 rounded-lg border border-border animate-pulse bg-muted/30" />
      </div>
    );
  }

  if (!platforms || platforms.length === 0) {
    return (
      <div className="space-y-6 pt-4">
        <div className="rounded-md border border-border p-8 text-center text-muted-foreground">
          <p className="text-sm">No platform data yet — traces from different IDEs will populate this view.</p>
        </div>
      </div>
    );
  }

  const platform = platforms[selected];
  const bestLatency = Math.min(...platforms.map((p) => p.avg_latency_ms || Infinity));
  const bestCost = Math.min(...platforms.filter((p) => p.avg_cost > 0).map((p) => p.avg_cost));
  const radarData = deriveRadarData(platform, { latency: bestLatency, cost: bestCost || 1 });

  const chartData = platforms.map((p, i) => ({
    name: p.platform,
    sessions: p.sessions,
    color: COLORS[i % COLORS.length],
  }));

  return (
    <div className="space-y-6 pt-4">
      {/* Sessions Bar Chart — sorted by adoption (most used = most validated) */}
      <div className="rounded-lg border border-border p-4">
        <h3 className="text-sm font-medium mb-1">Platform Adoption</h3>
        <p className="text-xs text-muted-foreground mb-4">Sorted by usage volume — click a bar to view platform details</p>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={chartData} margin={{ top: 10, right: 10, bottom: 0, left: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" strokeOpacity={0.5} vertical={false} />
            <XAxis dataKey="name" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} tickFormatter={(v) => v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v} axisLine={false} tickLine={false} />
            <Tooltip formatter={(value) => [Number(value).toLocaleString(), "Sessions"]} contentStyle={{ background: "hsl(var(--background))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} cursor={{ fill: "hsl(var(--muted))", opacity: 0.3 }} />
            <Bar dataKey="sessions" radius={[6, 6, 0, 0]} barSize={48} onClick={(_, index) => setSelected(index)} className="cursor-pointer" activeBar={false}>
              {chartData.map((entry, i) => (
                <Cell key={i} fill={i === selected ? entry.color : `${entry.color}66`} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Detail + Radar */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Detail Card */}
        <div className="rounded-lg border border-border p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded" style={{ background: COLORS[selected % COLORS.length] }} />
              <h3 className="text-lg font-semibold">{platform.platform}</h3>
            </div>
            <div className="text-2xl font-bold tabular-nums" style={{ color: COLORS[selected % COLORS.length] }}>
              {(platform.sessions / 1000).toFixed(1)}K
              <span className="text-xs font-normal text-muted-foreground ml-1">sessions</span>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 pt-4 border-t border-border">
            <div className="text-center">
              <div className="text-lg font-bold">{(platform.sessions / 1000).toFixed(1)}K</div>
              <div className="text-xs text-muted-foreground">Sessions</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-green-600">${platform.avg_cost.toFixed(3)}</div>
              <div className="text-xs text-muted-foreground">Avg Cost/Task</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold">{platform.success_rate}%</div>
              <div className="text-xs text-muted-foreground">Success Rate</div>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 mt-4">
            <div className="text-center">
              <div className="text-lg font-bold">{platform.avg_latency_ms.toFixed(0)}ms</div>
              <div className="text-xs text-muted-foreground">Avg Latency</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold">{platform.error_rate}%</div>
              <div className="text-xs text-muted-foreground">Error Rate</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold">{platform.users}</div>
              <div className="text-xs text-muted-foreground">Users</div>
            </div>
          </div>
        </div>

        {/* Radar Chart */}
        <div className="rounded-lg border border-border p-4">
          <h3 className="text-sm font-medium mb-2">Performance Radar</h3>
          <ResponsiveContainer width="100%" height={300}>
            <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="80%">
              <PolarGrid stroke="hsl(var(--border))" strokeOpacity={0.5} />
              <PolarAngleAxis dataKey="metric" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} />
              <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
              <Radar
                dataKey="value"
                stroke={COLORS[selected % COLORS.length]}
                fill={COLORS[selected % COLORS.length]}
                fillOpacity={0.2}
                strokeWidth={2.5}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Comparison Table */}
      <div className="rounded-lg border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/30">
              <th className="text-left p-3 font-medium">Platform</th>
              <th className="text-left p-3 font-medium">Sessions</th>
              <th className="text-left p-3 font-medium">Users</th>
              <th className="text-left p-3 font-medium">Avg Cost</th>
              <th className="text-left p-3 font-medium">Success</th>
              <th className="text-left p-3 font-medium">Latency</th>
            </tr>
          </thead>
          <tbody>
            {platforms.map((p, i) => (
              <tr
                key={p.platform}
                className={`border-b border-border cursor-pointer hover:bg-muted/20 ${i === selected ? "bg-muted/40" : ""}`}
                onClick={() => setSelected(i)}
              >
                <td className="p-3 font-medium">
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-sm" style={{ background: COLORS[i % COLORS.length] }} />
                    {p.platform}
                  </div>
                </td>
                <td className="p-3 tabular-nums font-semibold">{p.sessions >= 1000 ? `${(p.sessions / 1000).toFixed(1)}K` : p.sessions}</td>
                <td className="p-3 tabular-nums">{p.users}</td>
                <td className="p-3 tabular-nums font-mono text-xs">${p.avg_cost.toFixed(3)}</td>
                <td className="p-3 tabular-nums">{p.success_rate}%</td>
                <td className="p-3 tabular-nums">{p.avg_latency_ms.toFixed(0)}ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Model Provider Comparison */}
      <ModelComparison />
    </div>
  );
}

function ModelComparison() {
  const { data: insights } = useExecStrategicInsights();
  const [selectedModel, setSelectedModel] = useState(0);

  const models = insights?.model_comparison ?? [];

  if (models.length === 0) return null;

  const model = models[selectedModel];
  const maxSessions = Math.max(...models.map((m) => m.sessions)) || 1;

  const radarData = [
    { metric: "Success Rate", value: model?.success_rate ?? 0 },
    { metric: "Cost Efficiency", value: model ? Math.max(0, 100 - (model.avg_cost * 2000)) : 0 },
    { metric: "Token Efficiency", value: model ? Math.max(0, 100 - (model.avg_tokens / 100)) : 0 },
    { metric: "Volume", value: model ? (model.sessions / maxSessions) * 100 : 0 },
  ];

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border p-4">
        <h3 className="text-sm font-medium mb-1">Model Provider Comparison</h3>
        <p className="text-xs text-muted-foreground mb-4">Performance and cost by AI model (from actual usage)</p>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Model list */}
          <div className="space-y-2">
            {models.slice(0, 8).map((m, i) => (
              <div
                key={m.model}
                onClick={() => setSelectedModel(i)}
                className={`flex items-center justify-between p-3 rounded-md border cursor-pointer transition-colors ${
                  i === selectedModel ? "border-primary bg-primary/5" : "border-border hover:bg-muted/20"
                }`}
              >
                <div>
                  <p className="text-sm font-medium">{m.model}</p>
                  <p className="text-[11px] text-muted-foreground">{m.best_at}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-semibold tabular-nums">${m.avg_cost.toFixed(4)}</p>
                  <p className="text-[11px] text-muted-foreground">{m.success_rate}% · {m.sessions} sessions</p>
                </div>
              </div>
            ))}
          </div>

          {/* Radar for selected model */}
          <div>
            <ResponsiveContainer width="100%" height={260}>
              <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="80%">
                <PolarGrid stroke="hsl(var(--border))" strokeOpacity={0.5} />
                <PolarAngleAxis dataKey="metric" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} />
                <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                <Radar
                  dataKey="value"
                  stroke={COLORS[selectedModel % COLORS.length]}
                  fill={COLORS[selectedModel % COLORS.length]}
                  fillOpacity={0.2}
                  strokeWidth={2.5}
                />
              </RadarChart>
            </ResponsiveContainer>
            <div className="text-center mt-2">
              <p className="text-sm font-semibold">{model?.model}</p>
              <p className="text-xs text-muted-foreground">{model?.avg_tokens.toLocaleString()} avg tokens/session</p>
            </div>
          </div>
        </div>
      </div>

      {/* Model comparison table */}
      <div className="rounded-lg border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/30">
              <th className="text-left p-3 font-medium">Model</th>
              <th className="text-left p-3 font-medium">Sessions</th>
              <th className="text-left p-3 font-medium">Avg Cost</th>
              <th className="text-left p-3 font-medium">Avg Tokens</th>
              <th className="text-left p-3 font-medium">Success Rate</th>
              <th className="text-left p-3 font-medium">Best For</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m, i) => (
              <tr
                key={m.model}
                className={`border-b border-border cursor-pointer hover:bg-muted/20 ${i === selectedModel ? "bg-muted/40" : ""}`}
                onClick={() => setSelectedModel(i)}
              >
                <td className="p-3 font-medium">{m.model}</td>
                <td className="p-3 tabular-nums">{m.sessions.toLocaleString()}</td>
                <td className="p-3 tabular-nums font-mono text-xs">${m.avg_cost.toFixed(4)}</td>
                <td className="p-3 tabular-nums">{m.avg_tokens.toLocaleString()}</td>
                <td className="p-3 tabular-nums">{m.success_rate}%</td>
                <td className="p-3 text-xs text-muted-foreground">{m.best_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
