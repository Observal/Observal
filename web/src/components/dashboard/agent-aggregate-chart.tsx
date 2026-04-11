"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";

import type { AgentAggregate } from "@/lib/types";

interface AgentAggregateChartProps {
  data: AgentAggregate;
}

export function AgentAggregateChart({ data }: AgentAggregateChartProps) {
  const chartData = data.trend.map((t) => ({
    timestamp: new Date(t.timestamp).toLocaleDateString(),
    composite: t.composite,
    ci_low: data.ci_low,
    ci_high: data.ci_high,
  }));

  if (chartData.length === 0) return null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span>
          Mean: <strong className="text-foreground font-[family-name:var(--font-mono)] tabular-nums">{data.mean.toFixed(1)}</strong>/100
        </span>
        <span>
          CI: <span className="font-[family-name:var(--font-mono)] tabular-nums">[{data.ci_low.toFixed(1)}, {data.ci_high.toFixed(1)}]</span>
        </span>
        {data.drift_alert && (
          <DriftBadge driftAlert />
        )}
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={chartData}>
          <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" opacity={0.5} />
          <XAxis
            dataKey="timestamp"
            tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
            axisLine={{ stroke: "var(--color-border)" }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
            axisLine={false}
            tickLine={false}
            width={32}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--color-card)",
              border: "1px solid var(--color-border)",
              borderRadius: "6px",
              fontSize: "12px",
            }}
          />
          <ReferenceLine y={data.ci_low} stroke="var(--color-muted-foreground)" strokeDasharray="4 4" strokeOpacity={0.5} />
          <ReferenceLine y={data.ci_high} stroke="var(--color-muted-foreground)" strokeDasharray="4 4" strokeOpacity={0.5} />
          <Area
            type="monotone"
            dataKey="composite"
            stroke="var(--color-primary-accent)"
            fill="var(--color-primary-accent)"
            fillOpacity={0.15}
            strokeWidth={1.5}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DriftBadge({ driftAlert }: { driftAlert: boolean }) {
  if (!driftAlert) return null;
  return (
    <span className="inline-flex items-center rounded-md bg-destructive/15 px-1.5 py-0.5 text-[10px] font-medium text-destructive">
      Drift Detected
    </span>
  );
}
