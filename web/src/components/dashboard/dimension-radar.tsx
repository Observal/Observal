"use client";

import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

interface DimensionRadarProps {
  dimensionScores: Record<string, number>;
}

const DIMENSION_LABELS: Record<string, string> = {
  goal_completion: "Goal",
  tool_efficiency: "Efficiency",
  tool_failures: "Failures",
  factual_grounding: "Grounding",
  thought_process: "Thought",
};

export function DimensionRadar({ dimensionScores }: DimensionRadarProps) {
  const data = Object.entries(dimensionScores).map(([key, value]) => ({
    dimension: DIMENSION_LABELS[key] || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    score: value,
    fullMark: 100,
  }));

  if (data.length === 0) return null;

  return (
    <ResponsiveContainer width="100%" height={260}>
      <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
        <PolarGrid stroke="var(--color-border)" />
        <PolarAngleAxis
          dataKey="dimension"
          tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
        />
        <PolarRadiusAxis
          angle={90}
          domain={[0, 100]}
          tick={{ fontSize: 9, fill: "var(--color-muted-foreground)" }}
          axisLine={false}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: "6px",
            fontSize: "12px",
          }}
          formatter={(value) => [typeof value === "number" ? `${value.toFixed(0)}/100` : "-", "Score"]}
        />
        <Radar
          name="Score"
          dataKey="score"
          stroke="var(--color-primary-accent)"
          fill="var(--color-primary-accent)"
          fillOpacity={0.2}
          strokeWidth={1.5}
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}
