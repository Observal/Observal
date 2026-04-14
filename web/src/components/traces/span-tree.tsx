"use client";

import { useState, useMemo, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export interface Span {
  span_id: string;
  trace_id: string;
  parent_span_id?: string | null;
  type: string;
  name: string;
  method?: string;
  input?: unknown;
  output?: unknown;
  error?: string | null;
  start_time: string;
  end_time?: string;
  latency_ms?: number;
  status: string;
  metadata?: Record<string, unknown>;
  token_input?: number;
  token_output?: number;
  tool_schema_valid?: boolean;
}

interface SpanNode {
  span: Span;
  children: SpanNode[];
}

function buildTree(spans: Span[]): SpanNode[] {
  const map = new Map<string, SpanNode>();
  const roots: SpanNode[] = [];
  for (const span of spans) {
    map.set(span.span_id, { span, children: [] });
  }
  for (const span of spans) {
    const node = map.get(span.span_id)!;
    if (span.parent_span_id && map.has(span.parent_span_id)) {
      map.get(span.parent_span_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

function countDescendants(node: SpanNode): number {
  let count = 0;
  for (const child of node.children) {
    count += 1 + countDescendants(child);
  }
  return count;
}

const threadColor: Record<string, { line: string; hover: string; bg: string }> = {
  tool_call:    { line: "bg-blue-400",   hover: "bg-blue-500",   bg: "bg-blue-100 text-blue-700" },
  llm:          { line: "bg-purple-400", hover: "bg-purple-500", bg: "bg-purple-100 text-purple-700" },
  retrieval:    { line: "bg-amber-400",  hover: "bg-amber-500",  bg: "bg-amber-100 text-amber-700" },
  sandbox_exec: { line: "bg-green-400",  hover: "bg-green-500",  bg: "bg-green-100 text-green-700" },
  hook:         { line: "bg-pink-400",   hover: "bg-pink-500",   bg: "bg-pink-100 text-pink-700" },
  prompt:       { line: "bg-teal-400",   hover: "bg-teal-500",   bg: "bg-teal-100 text-teal-700" },
  lifecycle:    { line: "bg-gray-300",   hover: "bg-gray-400",   bg: "bg-gray-100 text-gray-500" },
};

function isLifecycleSpan(span: Span): boolean {
  return span.input == null && span.output == null;
}

function getColors(type: string) {
  return threadColor[type] ?? { line: "bg-gray-300", hover: "bg-gray-400", bg: "bg-gray-100 text-gray-700" };
}

function statusDot(status: string) {
  const color =
    status === "error" ? "bg-red-500" :
    status === "timeout" ? "bg-yellow-500" :
    "bg-green-500";
  return <span className={cn("inline-block h-2 w-2 rounded-full shrink-0", color)} />;
}

const INDENT = 20;

function SpanRow({
  node,
  depth,
  selectedId,
  onSelect,
  collapsed,
  onToggleCollapse,
  matchingSpanIds,
}: {
  node: SpanNode;
  depth: number;
  selectedId?: string;
  onSelect: (span: Span) => void;
  collapsed: Set<string>;
  onToggleCollapse: (id: string) => void;
  matchingSpanIds: Set<string> | null;
}) {
  const hasChildren = node.children.length > 0;
  const isCollapsed = collapsed.has(node.span.span_id);
  const isSelected = selectedId === node.span.span_id;
  const isLifecycle = isLifecycleSpan(node.span);
  const colors = isLifecycle ? threadColor.lifecycle : getColors(node.span.type);
  const descendantCount = isCollapsed ? countDescendants(node) : 0;
  const tokens = (node.span.token_input ?? 0) + (node.span.token_output ?? 0);
  const isAncestorOnly = matchingSpanIds !== null && !matchingSpanIds.has(node.span.span_id);

  return (
    <>
      {/* Span row */}
      <div className="relative">
        {/* Thread lines for each ancestor depth — rendered as absolute positioned lines */}
        {Array.from({ length: depth }, (_, i) => (
          <div
            key={i}
            className="absolute top-0 bottom-0 w-0.5 bg-gray-200 dark:bg-gray-700"
            style={{ left: `${i * INDENT + 11}px` }}
          />
        ))}

        {/* Clickable thread line for THIS node (only if it has children) */}
        {hasChildren && (
          <div
            role="button"
            tabIndex={0}
            onClick={(e) => { e.stopPropagation(); onToggleCollapse(node.span.span_id); }}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggleCollapse(node.span.span_id); } }}
            className={cn(
              "absolute z-10 cursor-pointer group/line",
              isCollapsed ? "top-3 bottom-0" : "top-3 bottom-0"
            )}
            style={{ left: `${depth * INDENT + 10}px`, width: "12px" }}
            title={isCollapsed ? "Expand children" : "Collapse children"}
          >
            <div
              className={cn(
                "absolute left-[5px] top-0 bottom-0 w-0.5 transition-all rounded-full",
                colors.line,
                "group-hover/line:w-[3px] group-hover/line:left-[4px]",
                `group-hover/line:${colors.hover}`
              )}
            />
          </div>
        )}

        <button
          onClick={() => onSelect(node.span)}
          className={cn(
            "flex w-full items-center gap-2 rounded px-2 py-1 text-sm hover:bg-muted/60 relative",
            isSelected && "bg-muted",
            isLifecycle && "opacity-50",
            isAncestorOnly && "opacity-40"
          )}
          style={{ paddingLeft: `${depth * INDENT + 8}px` }}
        >
          {statusDot(node.span.status)}
          <span className="truncate">{node.span.name}</span>
          {isCollapsed && (
            <span className="text-[10px] text-muted-foreground whitespace-nowrap">[+{descendantCount}]</span>
          )}
          <Badge variant="outline" className={cn("ml-auto text-[10px] px-1.5 py-0 shrink-0", colors.bg)}>
            {isLifecycle ? "lifecycle" : node.span.type}
          </Badge>
          {node.span.latency_ms != null && (
            <span className="text-xs text-muted-foreground tabular-nums shrink-0">{node.span.latency_ms}ms</span>
          )}
          {tokens > 0 && (
            <span className="text-xs text-muted-foreground tabular-nums shrink-0">{tokens}tok</span>
          )}
        </button>
      </div>

      {/* Children */}
      {hasChildren && !isCollapsed &&
        node.children.map((child) => (
          <SpanRow
            key={child.span.span_id}
            node={child}
            depth={depth + 1}
            selectedId={selectedId}
            onSelect={onSelect}
            collapsed={collapsed}
            onToggleCollapse={onToggleCollapse}
            matchingSpanIds={matchingSpanIds}
          />
        ))
      }
    </>
  );
}

interface SpanTreeProps {
  spans: Span[];
  selectedId?: string;
  onSelect: (span: Span) => void;
}

export function SpanTree({ spans, selectedId, onSelect }: SpanTreeProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [agentFilter, setAgentFilter] = useState("all");
  const [modelFilter, setModelFilter] = useState("all");

  const onToggleCollapse = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // Extract unique agent and model names from span metadata
  const { agentNames, modelNames } = useMemo(() => {
    const agents = new Set<string>();
    const models = new Set<string>();
    for (const span of spans) {
      const agent =
        (span.metadata?.["agent_name"] as string | undefined) ??
        (span.metadata?.["agent.name"] as string | undefined);
      if (agent) agents.add(agent);
      const model =
        (span.metadata?.["gen_ai.request.model"] as string | undefined) ??
        (span.metadata?.["model"] as string | undefined);
      if (model) models.add(model);
    }
    return {
      agentNames: Array.from(agents).sort(),
      modelNames: Array.from(models).sort(),
    };
  }, [spans]);

  const hasFilterableData = agentNames.length > 0 || modelNames.length > 0;
  const filtersActive = agentFilter !== "all" || modelFilter !== "all";

  // Build parent lookup for ancestor expansion
  const parentMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const span of spans) {
      if (span.parent_span_id) {
        map.set(span.span_id, span.parent_span_id);
      }
    }
    return map;
  }, [spans]);

  // Compute matching and visible span IDs
  const { matchingSpanIds, visibleSpanIds } = useMemo(() => {
    if (!filtersActive) {
      return { matchingSpanIds: null, visibleSpanIds: null };
    }

    const matching = new Set<string>();
    for (const span of spans) {
      const agent =
        (span.metadata?.["agent_name"] as string | undefined) ??
        (span.metadata?.["agent.name"] as string | undefined);
      const model =
        (span.metadata?.["gen_ai.request.model"] as string | undefined) ??
        (span.metadata?.["model"] as string | undefined);

      const agentMatch = agentFilter === "all" || agent === agentFilter;
      const modelMatch = modelFilter === "all" || model === modelFilter;

      if (agentMatch && modelMatch) {
        matching.add(span.span_id);
      }
    }

    // Expand to include all ancestors
    const visible = new Set(matching);
    for (const id of matching) {
      let current = parentMap.get(id);
      while (current) {
        if (visible.has(current)) break;
        visible.add(current);
        current = parentMap.get(current);
      }
    }

    return { matchingSpanIds: matching, visibleSpanIds: visible };
  }, [spans, agentFilter, modelFilter, filtersActive, parentMap]);

  // Filter spans to only visible ones and build tree
  const filteredSpans = useMemo(() => {
    if (!visibleSpanIds) return spans;
    return spans.filter((s) => visibleSpanIds.has(s.span_id));
  }, [spans, visibleSpanIds]);

  const roots = useMemo(() => buildTree(filteredSpans), [filteredSpans]);

  if (spans.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">No spans</p>;
  }

  return (
    <div className="py-2">
      {hasFilterableData && (
        <div className="flex items-center gap-2 px-2 pb-2">
          {agentNames.length > 0 && (
            <Select value={agentFilter} onValueChange={setAgentFilter}>
              <SelectTrigger className="h-7 w-[160px] text-xs">
                <SelectValue placeholder="Agent" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all" className="text-xs">All agents</SelectItem>
                {agentNames.map((name) => (
                  <SelectItem key={name} value={name} className="text-xs">
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {modelNames.length > 0 && (
            <Select value={modelFilter} onValueChange={setModelFilter}>
              <SelectTrigger className="h-7 w-[160px] text-xs">
                <SelectValue placeholder="Model" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all" className="text-xs">All models</SelectItem>
                {modelNames.map((name) => (
                  <SelectItem key={name} value={name} className="text-xs">
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {filtersActive && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={() => {
                setAgentFilter("all");
                setModelFilter("all");
              }}
            >
              Clear filters
            </Button>
          )}
        </div>
      )}
      {roots.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">No spans match filters</p>
      ) : (
        roots.map((node) => (
          <SpanRow
            key={node.span.span_id}
            node={node}
            depth={0}
            selectedId={selectedId}
            onSelect={onSelect}
            collapsed={collapsed}
            onToggleCollapse={onToggleCollapse}
            matchingSpanIds={matchingSpanIds}
          />
        ))
      )}
    </div>
  );
}
