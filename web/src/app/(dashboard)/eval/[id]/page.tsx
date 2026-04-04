"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { eval_ } from "@/lib/api";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

interface Dimension {
  name: string;
  score: number;
  comment?: string;
}

interface Scorecard {
  id: string;
  agent_id?: string;
  agent_name?: string;
  version?: string;
  status?: string;
  overall_score?: number;
  created_at?: string;
  dimensions?: Dimension[];
  metadata?: Record<string, unknown>;
}

export default function ScorecardDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: scorecard, isLoading } = useQuery({
    queryKey: ["eval", "scorecard", id],
    queryFn: () => eval_.show(id) as Promise<Scorecard>,
  });

  if (isLoading) {
    return <DashboardShell><Skeleton className="h-8 w-48 mb-4" /><Skeleton className="h-[400px] w-full" /></DashboardShell>;
  }
  if (!scorecard) {
    return <DashboardShell><p className="text-muted-foreground">Scorecard not found.</p></DashboardShell>;
  }

  const dims = scorecard.dimensions ?? [];

  return (
    <DashboardShell>
      <PageHeader
        title={`Scorecard ${id.slice(0, 8)}…`}
        breadcrumbs={[{ label: "Dashboard", href: "/" }, { label: "Evaluations", href: "/eval" }, { label: id.slice(0, 8) }]}
      />

      <div className="grid gap-4 md:grid-cols-4">
        <Card><CardContent className="pt-4"><p className="text-sm text-muted-foreground">Agent</p><p className="font-medium">{scorecard.agent_name ?? scorecard.agent_id ?? "—"}</p></CardContent></Card>
        <Card><CardContent className="pt-4"><p className="text-sm text-muted-foreground">Version</p><p className="font-medium">{scorecard.version ?? "—"}</p></CardContent></Card>
        <Card><CardContent className="pt-4"><p className="text-sm text-muted-foreground">Status</p><Badge variant={scorecard.status === "completed" ? "secondary" : "outline"}>{scorecard.status}</Badge></CardContent></Card>
        <Card><CardContent className="pt-4"><p className="text-sm text-muted-foreground">Overall Score</p><p className="text-2xl font-bold">{scorecard.overall_score?.toFixed(2) ?? "—"}</p></CardContent></Card>
      </div>

      {dims.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Dimension Scores</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={dims}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis domain={[0, 1]} />
                <Tooltip />
                <Bar dataKey="score" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {dims.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Details</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-3">
              {dims.map((d) => (
                <div key={d.name} className="flex items-start justify-between border-b pb-2 last:border-0">
                  <div>
                    <p className="font-medium">{d.name}</p>
                    {d.comment && <p className="text-sm text-muted-foreground">{d.comment}</p>}
                  </div>
                  <span className="font-mono text-sm">{d.score.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </DashboardShell>
  );
}
