"use client";

import { useState, useMemo } from "react";
import { MessageSquarePlus } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { useUnannotatedTraces, useSubmitFeedback } from "@/hooks/use-api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import { NoData } from "@/components/dashboard/no-data";

interface TraceRow {
  id: string;
  traceId: string;
  name?: string;
  trace_type?: string;
  traceType?: string;
  startTime?: string;
  start_time?: string;
  status?: string;
  scores?: Record<string, number>;
  annotated?: boolean;
}

const DIMENSIONS = ["tool_selection", "prompt_quality", "code_correctness", "rag_relevance"];

export default function AnnotationsPage() {
  const { data: traces, isLoading } = useUnannotatedTraces();
  const submitFeedback = useSubmitFeedback();
  const [filter, setFilter] = useState<"all" | "annotated" | "unannotated">("all");
  const [dialogTrace, setDialogTrace] = useState<TraceRow | null>(null);
  const [score, setScore] = useState(3);
  const [dimension, setDimension] = useState(DIMENSIONS[0]);
  const [comment, setComment] = useState("");

  const items = (traces ?? []) as TraceRow[];
  const filtered = useMemo(() => {
    if (filter === "all") return items;
    if (filter === "annotated") return items.filter((t) => t.annotated || (t.scores && Object.keys(t.scores).length > 0));
    return items.filter((t) => !t.annotated && (!t.scores || Object.keys(t.scores).length === 0));
  }, [items, filter]);

  const handleSubmit = async () => {
    if (!dialogTrace) return;
    await submitFeedback.mutateAsync({
      listing_type: "trace",
      listing_id: dialogTrace.traceId ?? dialogTrace.id,
      stars: score,
      comment: `[${dimension}] ${comment}`.trim(),
    });
    setDialogTrace(null);
    setScore(3);
    setComment("");
    setDimension(DIMENSIONS[0]);
  };

  return (
    <DashboardShell>
      <PageHeader
        title="Annotations"
        breadcrumbs={[{ label: "Home", href: "/" }, { label: "Annotations" }]}
      />
      <DashboardContent>
        <div className="flex flex-col gap-3">
          {/* Filter */}
          <div className="flex items-center gap-2">
            <Select value={filter} onValueChange={(v) => setFilter(v as typeof filter)}>
              <SelectTrigger className="h-8 w-[160px] text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all" className="text-sm">All traces</SelectItem>
                <SelectItem value="unannotated" className="text-sm">Unannotated</SelectItem>
                <SelectItem value="annotated" className="text-sm">Annotated</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Table */}
          {isLoading ? (
            <NoData isLoading />
          ) : !filtered.length ? (
            <NoData
              noDataText="No traces to annotate"
              description="Traces will appear here once telemetry is collected."
            />
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="h-9 px-3 text-xs">Name</TableHead>
                    <TableHead className="h-9 px-3 text-xs">Type</TableHead>
                    <TableHead className="h-9 px-3 text-xs">Time</TableHead>
                    <TableHead className="h-9 px-3 text-xs">Scores</TableHead>
                    <TableHead className="h-9 px-3 text-xs" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((t) => {
                    const traceId = t.traceId ?? t.id;
                    const type = t.trace_type ?? t.traceType ?? "";
                    const ts = t.startTime ?? t.start_time;
                    const scores = t.scores ?? {};
                    const scoreKeys = Object.keys(scores);
                    return (
                      <TableRow key={traceId}>
                        <TableCell className="px-3 py-2 text-sm">
                          {t.name ?? traceId.slice(0, 12)}
                        </TableCell>
                        <TableCell className="px-3 py-2">
                          {type && <Badge variant="outline" className="text-[10px]">{type}</Badge>}
                        </TableCell>
                        <TableCell className="px-3 py-2 text-xs text-muted-foreground">
                          {ts ? new Date(ts).toLocaleString() : "—"}
                        </TableCell>
                        <TableCell className="px-3 py-2">
                          {scoreKeys.length > 0 ? (
                            <div className="flex gap-1">
                              {scoreKeys.map((k) => (
                                <Badge key={k} variant="secondary" className="text-[10px]">
                                  {k}: {scores[k]}
                                </Badge>
                              ))}
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell className="px-3 py-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setDialogTrace(t)}
                          >
                            <MessageSquarePlus className="mr-1 h-3 w-3" />
                            Annotate
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </div>

        {/* Annotation dialog */}
        <Dialog open={!!dialogTrace} onOpenChange={(open) => !open && setDialogTrace(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Annotate Trace</DialogTitle>
              <DialogDescription>
                {dialogTrace?.name ?? dialogTrace?.traceId?.slice(0, 12) ?? ""}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <Label className="text-xs">Score (1–5)</Label>
                <div className="mt-1 flex gap-1">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <Button
                      key={n}
                      variant={score === n ? "default" : "outline"}
                      size="sm"
                      className="h-8 w-8 p-0"
                      onClick={() => setScore(n)}
                    >
                      {n}
                    </Button>
                  ))}
                </div>
              </div>
              <div>
                <Label className="text-xs">Dimension</Label>
                <Select value={dimension} onValueChange={setDimension}>
                  <SelectTrigger className="mt-1 h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DIMENSIONS.map((d) => (
                      <SelectItem key={d} value={d} className="text-sm">
                        {d.replace(/_/g, " ")}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs">Comment</Label>
                <Textarea
                  className="mt-1 text-sm"
                  placeholder="Optional notes…"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={3}
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" size="sm" onClick={() => setDialogTrace(null)}>
                Cancel
              </Button>
              <Button size="sm" disabled={submitFeedback.isPending} onClick={handleSubmit}>
                {submitFeedback.isPending ? "Submitting…" : "Submit"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </DashboardContent>
    </DashboardShell>
  );
}
