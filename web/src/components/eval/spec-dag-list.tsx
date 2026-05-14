// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
//
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useState } from "react";
import { ArrowUpFromLine, FileCode2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMigrateSpecDags, useSpecDags } from "@/hooks/use-api";
import type { SpecDagRow } from "@/lib/types";

const SOURCE_PILL: Record<string, string> = {
  hand_authored: "bg-info/15 text-info",
  mined: "bg-success/15 text-success",
  llm_inferred: "bg-warning/15 text-warning",
};

export function SpecDagList() {
  const [taskType, setTaskType] = useState("cancel_order");
  const { data, isLoading } = useSpecDags(taskType);
  const migrate = useMigrateSpecDags();
  const rows = (data ?? []) as SpecDagRow[];

  return (
    <div className="rounded-lg border border-border bg-card flex flex-col">
      <div className="border-b border-border px-3 py-2.5">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <FileCode2 className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold">Registered Versions</h3>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={!taskType.trim() || migrate.isPending}
            onClick={() => migrate.mutate(taskType)}
            title="Migrate v1 (path-oriented) → v2 (outcome-oriented)"
          >
            <ArrowUpFromLine className="h-3.5 w-3.5 mr-1.5" />
            {migrate.isPending ? "Migrating…" : "Migrate v1"}
          </Button>
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            value={taskType}
            onChange={(e) => setTaskType(e.target.value)}
            placeholder="Filter by task type"
            className="pl-7 font-[family-name:var(--font-mono)] text-xs h-8"
          />
        </div>
      </div>
      <div className="max-h-[420px] overflow-y-auto">
        {isLoading ? (
          <div className="p-3 text-xs text-muted-foreground">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="p-4 text-xs text-muted-foreground italic">
            No Spec DAGs registered for &ldquo;{taskType}&rdquo;.
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {rows.map((r) => (
              <li key={r.id} className="px-3 py-2.5 hover:bg-muted/40 transition-colors">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-[family-name:var(--font-mono)] text-sm font-semibold">
                    {r.task_type}
                    <span className="text-muted-foreground">@</span>
                    {r.version}
                  </span>
                  <span
                    className={`text-[10px] font-[family-name:var(--font-mono)] px-1.5 py-0.5 rounded ${SOURCE_PILL[r.source] || "bg-muted text-muted-foreground"}`}
                  >
                    {r.source}
                  </span>
                </div>
                <div className="text-[11px] text-muted-foreground mt-0.5 flex justify-between">
                  <span>{r.created_by || "—"}</span>
                  <span>{(r.created_at || "").slice(0, 10)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
