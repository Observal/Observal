// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { AlertTriangle, ShieldCheck, ShieldX, AlertCircle } from "lucide-react";
import type { ReviewItem, McpValidationResult } from "@/lib/types";

export function ValidationBadge({ item }: { item: ReviewItem }) {
  if (item.type !== "mcp" || !item.validation_results?.length) return null;

  const failed = item.validation_results.filter((v: McpValidationResult) => !v.passed);
  const hasWarnings = item.validation_results.some(
    (v: McpValidationResult) => v.details?.includes("Issues:"),
  );

  if (item.mcp_validated) {
    if (hasWarnings) {
      return (
        <span className="inline-flex items-center gap-1 text-[10px] text-amber-500 bg-amber-500/10 border border-amber-500/25 rounded px-1.5 py-0.5">
          <AlertTriangle className="h-3 w-3" /> Has warnings
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-success bg-success/10 border border-success/25 rounded px-1.5 py-0.5">
        <ShieldCheck className="h-3 w-3" /> Validated
      </span>
    );
  }

  if (failed.length > 0) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-destructive bg-destructive/10 border border-destructive/25 rounded px-1.5 py-0.5">
        <ShieldX className="h-3 w-3" /> Validation failed
      </span>
    );
  }

  return null;
}

export function ValidationDetails({ results }: { results?: McpValidationResult[] }) {
  if (!results?.length) return null;

  const issues = results
    .filter((v: McpValidationResult) => v.details)
    .flatMap((v: McpValidationResult) => {
      const lines = v.details!.split("\n");
      return lines
        .filter((l: string) => l.startsWith("- "))
        .map((l: string) => l.slice(2));
    });

  if (!issues.length) return null;

  return (
    <div className="mt-2 p-2 rounded bg-amber-500/5 border border-amber-500/15 space-y-1">
      <p className="text-[10px] font-medium text-amber-500 flex items-center gap-1">
        <AlertTriangle className="h-3 w-3" /> Quality warnings ({issues.length})
      </p>
      {issues.map((issue: string, i: number) => (
        <p key={i} className="text-[10px] text-muted-foreground pl-4">
          {issue}
        </p>
      ))}
    </div>
  );
}

export function ComponentReadinessBadge({ item }: { item: ReviewItem }) {
  if (item.components_ready !== false) return null;

  return (
    <div className="space-y-1.5">
      <span className="inline-flex items-center gap-1 text-[10px] text-destructive bg-destructive/10 border border-destructive/25 rounded px-1.5 py-0.5">
        <AlertCircle className="h-3 w-3" /> Components Not Ready
      </span>
      {item.component_blockers && item.component_blockers.length > 0 && (
        <div className="p-2 rounded bg-destructive/5 border border-destructive/15 space-y-1">
          <p className="text-[10px] font-medium text-destructive flex items-center gap-1">
            <AlertCircle className="h-3 w-3" /> Blocking components ({item.component_blockers.length})
          </p>
          {item.component_blockers.map((b, i) => (
            <p key={i} className="text-[10px] text-muted-foreground pl-4">
              {b.name} ({b.component_type}) — {b.status}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
