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
    dimension: DIMENSION_LABELS[key] || key,
    score: value,
    fullMark: 100,
  }));

  if (data.length === 0) return null;

  return (
    <ResponsiveContainer width="100%" height={300}>
      <RadarChart data={data}>
        <PolarGrid />
        <PolarAngleAxis dataKey="dimension" tick={{ fontSize: 12 }} />
        <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fontSize: 10 }} />
        <Tooltip formatter={(value) => [typeof value === "number" ? `${value.toFixed(0)}/100` : "—", "Score"]} />
        <Radar
          name="Score"
          dataKey="score"
          stroke="hsl(var(--primary))"
          fill="hsl(var(--primary))"
          fillOpacity={0.3}
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}
