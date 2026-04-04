"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { format, parseISO } from "date-fns";

interface TrendLine {
  key: string;
  color: string;
  label: string;
}

interface TrendChartProps {
  data: Array<{ date: string; [key: string]: number | string }>;
  lines: TrendLine[];
  height?: number;
}

export function TrendChart({ data, lines, height = 300 }: TrendChartProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="hsl(var(--muted-gray))"
          vertical={false}
        />
        <XAxis
          dataKey="date"
          tickFormatter={(v: string) => format(parseISO(v), "MMM d")}
          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          allowDecimals={false}
        />
        <Tooltip
          labelFormatter={(v) => format(parseISO(String(v)), "MMM d, yyyy")}
          contentStyle={{
            backgroundColor: "hsl(var(--popover))",
            border: "1px solid hsl(var(--border))",
            borderRadius: "6px",
            fontSize: "12px",
            padding: "8px 12px",
          }}
          itemStyle={{ padding: "2px 0" }}
        />
        <Legend
          iconType="circle"
          iconSize={8}
          wrapperStyle={{ fontSize: "12px", paddingTop: "8px" }}
        />
        {lines.map((line) => (
          <Line
            key={line.key}
            type="monotone"
            dataKey={line.key}
            name={line.label}
            stroke={line.color}
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3, strokeWidth: 0 }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
