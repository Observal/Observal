"use client";

import { useState, useCallback } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { TracePenalty } from "@/lib/types";

interface PenaltyAccordionProps {
  penalties: TracePenalty[];
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: "text-destructive",
  moderate: "text-warning",
  minor: "text-muted-foreground",
};

const SEVERITY_BG: Record<string, string> = {
  critical: "bg-destructive/10",
  moderate: "bg-warning/10",
  minor: "bg-muted/50",
};

function PenaltyItem({ penalty, isOpen, onToggle }: {
  penalty: TracePenalty;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const severity = penalty.severity || "minor";
  const colorClass = SEVERITY_COLORS[severity] || "";
  const bgClass = SEVERITY_BG[severity] || "bg-muted/50";

  return (
    <div className="rounded-md border border-border overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center justify-between w-full text-left p-3 hover:bg-muted/30 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/20"
      >
        <span className="flex items-center gap-2">
          {isOpen ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          )}
          <span className={`text-sm font-medium ${colorClass}`}>
            {penalty.event_name}
          </span>
        </span>
        <span className={`text-xs font-[family-name:var(--font-mono)] tabular-nums px-1.5 py-0.5 rounded ${bgClass} ${colorClass}`}>
          {penalty.amount > 0 ? `-${penalty.amount}` : penalty.amount}
        </span>
      </button>
      <div
        className="grid transition-all duration-[var(--duration-normal)]"
        style={{
          gridTemplateRows: isOpen ? "1fr" : "0fr",
        }}
      >
        <div className="overflow-hidden">
          <div className="px-3 pb-3 pt-0 ml-6 text-sm text-muted-foreground space-y-1.5">
            <p>
              <span className="text-xs text-foreground font-medium">Dimension:</span>{" "}
              <span className="text-xs">{penalty.dimension}</span>
            </p>
            <p>
              <span className="text-xs text-foreground font-medium">Evidence:</span>{" "}
              <span className="text-xs">{penalty.evidence}</span>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export function PenaltyAccordion({ penalties }: PenaltyAccordionProps) {
  const [openSet, setOpenSet] = useState<Set<number>>(new Set());

  const toggle = useCallback((index: number) => {
    setOpenSet((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }, []);

  if (penalties.length === 0) {
    return <p className="text-sm text-muted-foreground">No penalties applied.</p>;
  }

  return (
    <div className="space-y-2">
      {penalties.map((p, i) => (
        <PenaltyItem
          key={i}
          penalty={p}
          isOpen={openSet.has(i)}
          onToggle={() => toggle(i)}
        />
      ))}
    </div>
  );
}
