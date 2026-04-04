"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { RegistryType } from "@/lib/api";

function StatCard({ label, value }: { label: string; value: string | number | undefined }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-bold">{value ?? "—"}</p>
      </CardContent>
    </Card>
  );
}

const MCP_FIELDS = [
  ["total_downloads", "Downloads"],
  ["total_calls", "Total Calls"],
  ["error_rate", "Error Rate"],
  ["avg_latency", "Avg Latency"],
  ["p50", "p50"],
  ["p90", "p90"],
  ["p99", "p99"],
] as const;

const AGENT_FIELDS = [
  ["total_interactions", "Interactions"],
  ["total_downloads", "Downloads"],
  ["acceptance_rate", "Acceptance Rate"],
  ["avg_tool_calls", "Avg Tool Calls"],
  ["avg_latency", "Avg Latency"],
] as const;

interface MetricsPanelProps {
  type: RegistryType;
  data: Record<string, unknown> | undefined;
  isLoading: boolean;
}

export function MetricsPanel({ type, data, isLoading }: MetricsPanelProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}><CardContent className="p-6"><Skeleton className="h-8 w-20" /></CardContent></Card>
        ))}
      </div>
    );
  }

  if (!data) return null;

  const fields = type === "mcps" ? MCP_FIELDS : type === "agents" ? AGENT_FIELDS : null;

  const entries = fields
    ? fields.map(([key, label]) => ({ label, value: data[key] }))
    : Object.entries(data).map(([key, value]) => ({
        label: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
        value,
      }));

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {entries.map((e) => (
        <StatCard key={e.label} label={e.label} value={String(e.value ?? "—")} />
      ))}
    </div>
  );
}
