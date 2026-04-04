"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { graphql } from "@/lib/api";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface Score {
  score_id: string;
  trace_id: string;
  span_id?: string;
  name: string;
  source: string;
  data_type: string;
  value?: number;
  string_value?: string;
  comment?: string;
  timestamp: string;
}

const SOURCES = ["all", "human", "eval"];

export default function ScoresPage() {
  const [source, setSource] = useState("all");
  const [nameFilter, setNameFilter] = useState("");

  const { data: scores, isLoading } = useQuery({
    queryKey: ["scores", source],
    queryFn: () =>
      graphql<{ scores: Score[] }>(
        `query Scores($source: String) { scores(source: $source) { score_id trace_id span_id name source data_type value string_value comment timestamp } }`,
        source !== "all" ? { source } : undefined,
      ).then((d) => d.scores),
  });

  const filtered = scores?.filter((s) => !nameFilter || s.name.toLowerCase().includes(nameFilter.toLowerCase()));

  return (
    <DashboardShell>
      <PageHeader title="Scores" breadcrumbs={[{ label: "Dashboard", href: "/" }, { label: "Scores" }]} />

      <div className="flex gap-3">
        <Input placeholder="Filter by name…" value={nameFilter} onChange={(e) => setNameFilter(e.target.value)} className="max-w-xs" />
        <Select value={source} onValueChange={setSource}>
          <SelectTrigger className="w-[140px]"><SelectValue /></SelectTrigger>
          <SelectContent>{SOURCES.map((s) => <SelectItem key={s} value={s}>{s === "all" ? "All sources" : s}</SelectItem>)}</SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Value</TableHead>
              <TableHead>Trace</TableHead>
              <TableHead>Timestamp</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered?.length ? filtered.map((s) => (
              <TableRow key={s.score_id}>
                <TableCell className="font-medium">{s.name}</TableCell>
                <TableCell><Badge variant={s.source === "human" ? "secondary" : "outline"}>{s.source}</Badge></TableCell>
                <TableCell>{s.data_type}</TableCell>
                <TableCell className="font-mono">{s.value != null ? s.value : s.string_value ?? "—"}</TableCell>
                <TableCell>
                  <Link href={`/traces/${s.trace_id}`} className="font-mono text-xs text-primary hover:underline">{s.trace_id.slice(0, 8)}…</Link>
                </TableCell>
                <TableCell className="text-xs">{new Date(s.timestamp).toLocaleString()}</TableCell>
              </TableRow>
            )) : (
              <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground">No scores found</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      )}
    </DashboardShell>
  );
}
