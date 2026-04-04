"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useEvalScorecards, useEvalRun } from "@/hooks/use-api";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";

interface Scorecard {
  id: string;
  agent_id?: string;
  agent_name?: string;
  version?: string;
  status?: string;
  overall_score?: number;
  created_at?: string;
  dimensions?: { label: string; score: number }[];
}

export default function EvalPage() {
  const router = useRouter();
  const [agentId, setAgentId] = useState("");
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [runAgentId, setRunAgentId] = useState("");

  const { data: scorecards, isLoading } = useEvalScorecards(agentId || undefined);
  const { mutate: runEval, isPending } = useEvalRun();

  const handleRun = () => {
    if (runAgentId.trim()) {
      runEval({ agentId: runAgentId }, { onSuccess: () => { setRunDialogOpen(false); setAgentId(runAgentId); } });
    }
  };

  return (
    <DashboardShell>
      <PageHeader title="Evaluations" breadcrumbs={[{ label: "Dashboard", href: "/" }, { label: "Evaluations" }]}>
        <Button onClick={() => setRunDialogOpen(true)}>Run Eval</Button>
      </PageHeader>
      <DashboardContent>

      <div className="flex gap-3">
        <Input placeholder="Agent ID to view scorecards…" value={agentId} onChange={(e) => setAgentId(e.target.value)} className="max-w-sm" />
      </div>

      {isLoading ? (
        <div className="space-y-2">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Agent</TableHead>
              <TableHead>Version</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(scorecards as Scorecard[] | undefined)?.length ? (scorecards as Scorecard[]).map((sc) => (
              <TableRow key={sc.id} className="cursor-pointer" onClick={() => router.push(`/eval/${sc.id}`)}>
                <TableCell>{sc.agent_name ?? sc.agent_id ?? "—"}</TableCell>
                <TableCell>{sc.version ?? "—"}</TableCell>
                <TableCell><Badge variant={sc.status === "completed" ? "secondary" : sc.status === "failed" ? "destructive" : "outline"}>{sc.status ?? "—"}</Badge></TableCell>
                <TableCell className="font-mono">{sc.overall_score != null ? sc.overall_score.toFixed(2) : "—"}</TableCell>
                <TableCell className="text-xs">{sc.created_at ? new Date(sc.created_at).toLocaleString() : "—"}</TableCell>
              </TableRow>
            )) : (
              <TableRow><TableCell colSpan={5} className="text-center text-muted-foreground">{agentId ? "No scorecards found" : "Enter an agent ID to view scorecards"}</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      )}

      <Dialog open={runDialogOpen} onOpenChange={setRunDialogOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Run Evaluation</DialogTitle></DialogHeader>
          <Input placeholder="Agent ID" value={runAgentId} onChange={(e) => setRunAgentId(e.target.value)} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRunDialogOpen(false)}>Cancel</Button>
            <Button disabled={isPending || !runAgentId.trim()} onClick={handleRun}>Run</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
          </DashboardContent>
    </DashboardShell>
  );
}
