"use client";

import { useState } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export interface HeatmapDatum {
  name: string;
  hour: number;
  p50: number;
  p90: number;
  p99: number;
}

type Metric = "p50" | "p90" | "p99";

interface LatencyHeatmapProps {
  data: HeatmapDatum[];
  metric?: Metric;
}

function cellColor(ms: number): string {
  if (ms < 100) return "bg-light-green";
  if (ms < 500) return "bg-light-yellow";
  if (ms < 1000) return "bg-[hsl(30,80%,90%)]";
  return "bg-light-red";
}

export function LatencyHeatmap({ data, metric: defaultMetric = "p50" }: LatencyHeatmapProps) {
  const [metric, setMetric] = useState<Metric>(defaultMetric);

  const names = [...new Set(data.map((d) => d.name))];
  const hours = [...new Set(data.map((d) => d.hour))].sort((a, b) => a - b);

  const lookup = new Map<string, number>();
  for (const d of data) lookup.set(`${d.name}-${d.hour}`, d[metric]);

  return (
    <div className="space-y-3">
      <Tabs value={metric} onValueChange={(v) => setMetric(v as Metric)}>
        <TabsList>
          <TabsTrigger value="p50">P50</TabsTrigger>
          <TabsTrigger value="p90">P90</TabsTrigger>
          <TabsTrigger value="p99">P99</TabsTrigger>
        </TabsList>
      </Tabs>

      {names.length === 0 ? (
        <p className="text-sm text-muted-foreground">No heatmap data.</p>
      ) : (
        <div className="overflow-x-auto">
          <TooltipProvider delayDuration={100}>
            <div className="inline-grid gap-0.5" style={{ gridTemplateColumns: `120px repeat(${hours.length}, 32px)` }}>
              {/* Header row */}
              <div />
              {hours.map((h) => (
                <div key={h} className="text-center text-[10px] text-muted-foreground">{h}h</div>
              ))}

              {/* Data rows */}
              {names.map((name) => (
                <>
                  <div key={`label-${name}`} className="truncate pr-2 text-xs font-medium leading-8">{name}</div>
                  {hours.map((h) => {
                    const val = lookup.get(`${name}-${h}`);
                    return (
                      <Tooltip key={`${name}-${h}`}>
                        <TooltipTrigger asChild>
                          <div className={cn("h-7 w-7 rounded-sm", val != null ? cellColor(val) : "bg-muted/30")} />
                        </TooltipTrigger>
                        <TooltipContent side="top" className="text-xs">
                          {val != null ? `${val}ms` : "No data"} — {name} @ {h}:00
                        </TooltipContent>
                      </Tooltip>
                    );
                  })}
                </>
              ))}
            </div>
          </TooltipProvider>

          {/* Legend */}
          <div className="mt-3 flex items-center gap-3 text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-sm bg-light-green" /> &lt;100ms</span>
            <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-sm bg-light-yellow" /> 100-500ms</span>
            <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-sm bg-[hsl(30,80%,90%)]" /> 500-1000ms</span>
            <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-sm bg-light-red" /> &gt;1000ms</span>
          </div>
        </div>
      )}
    </div>
  );
}
