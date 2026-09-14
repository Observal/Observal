// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { AlertTriangle, ShieldCheck, ShieldX, AlertCircle, Check, Minus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ReviewItem, McpValidationResult } from "@/lib/types";

/**
 * Tones for the three validation outcomes. `Badge` carries the shape, size and
 * type scale; only the semantic colour pairing differs per outcome, and each
 * one ships with its own icon and wording so the tone is never the only cue.
 */
export function componentBlockers(item: ReviewItem) {
  return item.component_blockers ?? item.blocking_components ?? [];
}

const toneClasses = {
  success: "border-success/25 bg-success/10 text-success",
  warning: "border-warning/25 bg-warning/10 text-warning",
  destructive: "border-destructive/25 bg-destructive/10 text-destructive",
} as const;

/** A callout listing the detail lines behind a badge. */
function IssueList({
  tone,
  icon: Icon,
  title,
  items,
}: {
  tone: "warning" | "destructive";
  icon: typeof AlertTriangle;
  title: string;
  items: string[];
}) {
  const surface =
    tone === "warning"
      ? "border-warning/15 bg-warning/5"
      : "border-destructive/15 bg-destructive/5";
  const heading = tone === "warning" ? "text-warning" : "text-destructive";

  return (
    <div className={cn("space-y-1 rounded border p-2", surface)}>
      <p className={cn("flex items-center gap-1 text-2xs font-medium", heading)}>
        <Icon className="h-3 w-3" /> {title} ({items.length})
      </p>
      {items.map((item, i) => (
        <p key={i} className="pl-4 text-2xs text-muted-foreground">
          {item}
        </p>
      ))}
    </div>
  );
}

export function ValidationBadge({ item }: { item: ReviewItem }) {
  if (item.type !== "mcp" || !item.validation_results?.length) return null;

  const failed = item.validation_results.filter((v: McpValidationResult) => !v.passed);
  const hasWarnings = item.validation_results.some(
    (v: McpValidationResult) => v.details?.includes("Issues:"),
  );

  if (item.mcp_validated) {
    if (hasWarnings) {
      return (
        <Badge variant="outline" className={toneClasses.warning}>
          <AlertTriangle className="h-3 w-3" /> Has warnings
        </Badge>
      );
    }
    return (
      <Badge variant="outline" className={toneClasses.success}>
        <ShieldCheck className="h-3 w-3" /> Validated
      </Badge>
    );
  }

  if (failed.length > 0) {
    return (
      <Badge variant="outline" className={toneClasses.destructive}>
        <ShieldX className="h-3 w-3" /> Validation failed
      </Badge>
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
    <div className="mt-2">
      <IssueList
        tone="warning"
        icon={AlertTriangle}
        title="Quality warnings"
        items={issues}
      />
    </div>
  );
}

export function ComponentReadinessBadge({ item }: { item: ReviewItem }) {
  if (item.components_ready !== false) return null;

  const blockers = componentBlockers(item);

  return (
    <div className="space-y-1.5">
      <Badge variant="outline" className={toneClasses.destructive}>
        <AlertCircle className="h-3 w-3" /> Components not ready
      </Badge>
      {blockers.length > 0 && (
        <IssueList
          tone="destructive"
          icon={AlertCircle}
          title="Blocking components"
          items={blockers.map((b) => `${b.name} (${b.component_type}) — ${b.status}`)}
        />
      )}
    </div>
  );
}

export function ValidationCheckCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "pass" | "fail" | "neutral";
}) {
  const Icon = tone === "pass" ? Check : tone === "fail" ? AlertTriangle : Minus;
  return (
    <div className="bg-surface-raised p-3.5">
      <span className="block text-4xs uppercase tracking-[0.05em] text-muted-foreground">
        {label}
      </span>
      <strong
        className={cn(
          "mt-1 flex items-center gap-1 text-2xs font-medium",
          tone === "pass"
            ? "text-success"
            : tone === "fail"
              ? "text-destructive"
              : "text-muted-foreground",
        )}
      >
        <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
        {value}
      </strong>
    </div>
  );
}
