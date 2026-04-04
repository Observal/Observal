"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Pause, Play } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { graphql } from "@/lib/api";
import { cn } from "@/lib/utils";

interface TraceItem {
  id: string;
  traceId: string;
  name: string;
  trace_type?: string;
  traceType?: string;
  ide?: string;
  startTime?: string;
  start_time?: string;
  status?: string;
}

const TYPE_COLORS: Record<string, string> = {
  mcp: "bg-blue-500",
  agent: "bg-purple-500",
  tool: "bg-green-500",
  skill: "bg-amber-500",
  hook: "bg-pink-500",
  prompt: "bg-cyan-500",
  sandbox: "bg-orange-500",
  graphrag: "bg-teal-500",
};

const TRACE_TYPES = ["all", "mcp", "agent", "tool", "skill", "hook", "prompt", "sandbox", "graphrag"];
const IDES = ["all", "cursor", "kiro", "kiro-cli", "claude-code", "gemini-cli", "vscode", "windsurf"];
const MAX_BUFFER = 200;

function relativeTime(ts: string): string {
  const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function TraceStream() {
  const router = useRouter();
  const [buffer, setBuffer] = useState<TraceItem[]>([]);
  const [paused, setPaused] = useState(false);
  const [newCount, setNewCount] = useState(0);
  const [typeFilter, setTypeFilter] = useState("all");
  const [ideFilter, setIdeFilter] = useState("all");
  const bottomRef = useRef<HTMLDivElement>(null);
  const seenIds = useRef(new Set<string>());
  const pendingRef = useRef<TraceItem[]>([]);

  const fetchTraces = useCallback(async () => {
    try {
      const filters: Record<string, unknown> = {};
      if (typeFilter !== "all") filters.trace_type = typeFilter;
      if (ideFilter !== "all") filters.ide = ideFilter;
      const data = await graphql<{ traces: TraceItem[] }>(
        `query Traces($filters: TraceFilters) { traces(filters: $filters) { id traceId startTime endTime status spanCount } }`,
        Object.keys(filters).length ? { filters } : undefined,
      );
      const incoming = (data.traces ?? []).filter((t) => {
        const key = t.traceId ?? t.id;
        if (seenIds.current.has(key)) return false;
        seenIds.current.add(key);
        return true;
      });
      if (!incoming.length) return;

      if (paused) {
        pendingRef.current = [...pendingRef.current, ...incoming].slice(-MAX_BUFFER);
        setNewCount((c) => c + incoming.length);
      } else {
        setBuffer((prev) => [...prev, ...incoming].slice(-MAX_BUFFER));
      }
    } catch {
      // silently ignore fetch errors
    }
  }, [typeFilter, ideFilter, paused]);

  useEffect(() => {
    fetchTraces();
    const id = setInterval(fetchTraces, 3000);
    return () => clearInterval(id);
  }, [fetchTraces]);

  useEffect(() => {
    if (!paused) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [buffer, paused]);

  const handleResume = () => {
    setBuffer((prev) => [...prev, ...pendingRef.current].slice(-MAX_BUFFER));
    pendingRef.current = [];
    setNewCount(0);
    setPaused(false);
  };

  const filtered = buffer.filter((t) => {
    const type = t.trace_type ?? t.traceType ?? "";
    const ide = t.ide ?? "";
    if (typeFilter !== "all" && type !== typeFilter) return false;
    if (ideFilter !== "all" && ide !== ideFilter) return false;
    return true;
  });

  return (
    <div className="flex h-full flex-col gap-3">
      {/* Filter bar */}
      <div className="flex items-center gap-2">
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="h-8 w-[140px] text-sm">
            <SelectValue placeholder="Trace type" />
          </SelectTrigger>
          <SelectContent>
            {TRACE_TYPES.map((t) => (
              <SelectItem key={t} value={t} className="text-sm">
                {t === "all" ? "All types" : t}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={ideFilter} onValueChange={setIdeFilter}>
          <SelectTrigger className="h-8 w-[140px] text-sm">
            <SelectValue placeholder="IDE" />
          </SelectTrigger>
          <SelectContent>
            {IDES.map((i) => (
              <SelectItem key={i} value={i} className="text-sm">
                {i === "all" ? "All IDEs" : i}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="ml-auto">
          {paused ? (
            <Button variant="outline" size="sm" onClick={handleResume}>
              <Play className="mr-1 h-3 w-3" />
              Resume{newCount > 0 && ` (${newCount} new)`}
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setPaused(true)}>
              <Pause className="mr-1 h-3 w-3" />
              Pause
            </Button>
          )}
        </div>
      </div>

      {/* Stream */}
      <ScrollArea className="flex-1 rounded-md border">
        <div className="divide-y">
          {filtered.length === 0 && (
            <p className="p-8 text-center text-sm text-muted-foreground">
              Waiting for traces…
            </p>
          )}
          {filtered.map((t) => {
            const traceId = t.traceId ?? t.id;
            const type = t.trace_type ?? t.traceType ?? "";
            const ts = t.startTime ?? t.start_time ?? "";
            return (
              <button
                key={traceId}
                className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/50"
                onClick={() => router.push(`/traces/${traceId}`)}
              >
                <span
                  className={cn(
                    "h-2 w-2 shrink-0 rounded-full",
                    TYPE_COLORS[type] ?? "bg-gray-400",
                  )}
                />
                <span className="min-w-0 flex-1 truncate text-sm">
                  {t.name ?? traceId.slice(0, 12)}
                </span>
                {type && (
                  <Badge variant="outline" className="shrink-0 text-[10px]">
                    {type}
                  </Badge>
                )}
                {t.ide && (
                  <Badge variant="secondary" className="shrink-0 text-[10px]">
                    {t.ide}
                  </Badge>
                )}
                {ts && (
                  <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                    {relativeTime(ts)}
                  </span>
                )}
              </button>
            );
          })}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
    </div>
  );
}
