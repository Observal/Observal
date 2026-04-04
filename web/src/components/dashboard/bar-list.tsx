"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface BarListItem {
  name: ReactNode;
  value: number;
}

interface BarListProps {
  data: BarListItem[];
  maxItems?: number;
  valueFormatter?: (v: number) => string;
}

export function BarList({ data, maxItems = 5, valueFormatter = (v) => String(v) }: BarListProps) {
  const [expanded, setExpanded] = useState(false);
  const maxValue = Math.max(...data.map((d) => d.value), 1);
  const visible = expanded ? data : data.slice(0, maxItems);

  return (
    <div className="space-y-1">
      {visible.map((item, i) => (
        <div key={i} className="group flex items-center gap-2 text-sm">
          <div className="relative flex min-w-0 flex-1 items-center">
            <div
              className="absolute inset-y-0 left-0 rounded-sm bg-primary-accent/10"
              style={{ width: `${(item.value / maxValue) * 100}%` }}
            />
            <span className="relative truncate py-1 pl-2 text-sm">{item.name}</span>
          </div>
          <span className="w-14 shrink-0 text-right tabular-nums text-xs text-muted-foreground">
            {valueFormatter(item.value)}
          </span>
        </div>
      ))}
      {data.length > maxItems && (
        <button
          className="flex w-full items-center justify-center gap-1 pt-1 text-xs text-muted-foreground hover:text-foreground"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? (
            <>Show less <ChevronUp className="h-3 w-3" /></>
          ) : (
            <>Show top {Math.min(data.length, 20)} <ChevronDown className="h-3 w-3" /></>
          )}
        </button>
      )}
    </div>
  );
}
