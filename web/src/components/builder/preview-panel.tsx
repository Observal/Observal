"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { ValidationResult } from "@/lib/types";

interface PreviewPanelProps {
  name: string;
  description: string;
  selectedComponents: Record<string, { id: string; name: string }[]>;
  goalSections: { id: string; title: string; content: string }[];
  validationResult: ValidationResult | null;
}

export function PreviewPanel({
  name,
  description,
  selectedComponents,
  goalSections,
  validationResult,
}: PreviewPanelProps) {
  const lines: string[] = [];

  lines.push(`name: ${name || "(untitled)"}`);
  if (description) {
    lines.push(`description: |`);
    description.split("\n").forEach((l) => lines.push(`  ${l}`));
  }

  const hasComponents = Object.values(selectedComponents).some(
    (arr) => arr.length > 0,
  );
  if (hasComponents) {
    lines.push("");
    lines.push("components:");
    for (const [type, items] of Object.entries(selectedComponents)) {
      if (items.length === 0) continue;
      lines.push(`  ${type}:`);
      items.forEach((item) => lines.push(`    - ${item.name}`));
    }
  }

  const nonEmptyGoals = goalSections.filter((s) => s.title || s.content);
  if (nonEmptyGoals.length > 0) {
    lines.push("");
    lines.push("goal:");
    nonEmptyGoals.forEach((section) => {
      lines.push(`  ${section.title || "(section)"}:`);
      if (section.content) {
        section.content
          .split("\n")
          .forEach((l) => lines.push(`    ${l}`));
      }
    });
  }

  const errorCount = validationResult
    ? validationResult.issues.filter((i) => i.severity === "error").length
    : 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
          Preview
        </h3>
        {validationResult && (
          <span className="inline-flex items-center gap-1 text-xs">
            {validationResult.valid ? (
              <>
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                <span className="text-emerald-600 dark:text-emerald-400">
                  Valid
                </span>
              </>
            ) : (
              <>
                <XCircle className="h-3.5 w-3.5 text-destructive" />
                <span className="text-destructive">
                  {errorCount} {errorCount === 1 ? "error" : "errors"}
                </span>
              </>
            )}
          </span>
        )}
      </div>
      <Card>
        <CardContent className="p-0">
          <pre className="min-h-[200px] whitespace-pre-wrap rounded-md border bg-muted/30 p-4 text-sm leading-relaxed font-[family-name:var(--font-mono)] text-foreground/80">
            {lines.join("\n")}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
