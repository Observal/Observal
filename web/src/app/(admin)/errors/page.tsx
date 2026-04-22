"use client";

import { useState, useMemo, useCallback, useRef } from "react";
import Link from "next/link";
import { AlertTriangle, Search, ChevronDown, ChevronRight, Wrench, Bot, Square } from "lucide-react";
import { useOtelErrors } from "@/hooks/use-api";
import type { OtelErrorEvent } from "@/lib/types";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { Input } from "@/components/ui/input";

/* ── Helpers ─────────────────────────────────────────────── */

type ErrorType = "tool_failure" | "stop_failure" | "api_error";

function classifyError(event: OtelErrorEvent): ErrorType {
  if (event.event_name === "hook_posttoolusefailure") return "tool_failure";
  if (event.event_name === "hook_stopfailure") return "stop_failure";
  return "api_error";
}

function errorTypeLabel(t: ErrorType): string {
  switch (t) {
    case "tool_failure": return "Tool Failure";
    case "stop_failure": return "Stop Failure";
    case "api_error": return "API Error";
  }
}

function errorTypeColor(t: ErrorType): string {
  switch (t) {
    case "tool_failure": return "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20";
    case "stop_failure": return "bg-red-500/10 text-red-500 border-red-500/20";
    case "api_error": return "bg-rose-500/10 text-rose-500 border-rose-500/20";
  }
}

function ErrorIcon({ type }: { type: ErrorType }) {
  switch (type) {
    case "tool_failure": return <Wrench className="h-3.5 w-3.5" />;
    case "stop_failure": return <Square className="h-3.5 w-3.5" />;
    case "api_error": return <AlertTriangle className="h-3.5 w-3.5" />;
  }
}

/* ── Error row ───────────────────────────────────────────── */

function ErrorRow({ event }: { event: OtelErrorEvent }) {
  const [expanded, setExpanded] = useState(false);
  const type = classifyError(event);
  const colorCls = errorTypeColor(type);

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-start gap-2.5 w-full text-left py-2.5 px-3 hover:bg-muted/30 transition-colors"
      >
        {expanded
          ? <ChevronDown className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          : <ChevronRight className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />}
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-medium border ${colorCls} shrink-0`}>
          <ErrorIcon type={type} />
          {errorTypeLabel(type)}
        </span>
        {event.tool_name && (
          <span className="text-xs font-medium bg-muted px-1.5 py-0.5 rounded shrink-0">
            {event.tool_name}
          </span>
        )}
        <span className="text-xs text-muted-foreground truncate flex-1">
          {event.error || event.body || "Unknown error"}
        </span>
        {event.agent_type && (
          <span className="text-[10px] bg-indigo-500/10 text-indigo-500 px-1.5 py-0.5 rounded shrink-0">
            <Bot className="h-2.5 w-2.5 inline mr-0.5" />{event.agent_type}
          </span>
        )}
        <span className="text-[10px] text-muted-foreground tabular-nums shrink-0 mt-0.5">
          {new Date(event.timestamp).toLocaleString()}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-border px-4 py-3 space-y-3 bg-muted/10">
          {/* Error detail */}
          {event.error && (
            <div className="space-y-1">
              <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Error</span>
              <pre className="text-xs font-[family-name:var(--font-mono)] whitespace-pre-wrap break-all bg-red-500/5 border border-red-500/20 rounded-md p-2.5 max-h-[200px] overflow-auto text-red-600 dark:text-red-400">
                {event.error}
              </pre>
            </div>
          )}

          {/* Tool input that caused the error */}
          {event.tool_input && (
            <div className="space-y-1">
              <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Tool Input</span>
              <pre className="text-xs font-[family-name:var(--font-mono)] whitespace-pre-wrap break-all bg-background/50 border border-border rounded-md p-2.5 max-h-[200px] overflow-auto">
                {(() => {
                  try { return JSON.stringify(JSON.parse(event.tool_input), null, 2); } catch { return event.tool_input; }
                })()}
              </pre>
            </div>
          )}

          {/* Tool response (may contain error details) */}
          {event.tool_response && (
            <div className="space-y-1">
              <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Tool Response</span>
              <pre className="text-xs font-[family-name:var(--font-mono)] whitespace-pre-wrap break-all bg-background/50 border border-border rounded-md p-2.5 max-h-[200px] overflow-auto">
                {event.tool_response.substring(0, 2000)}
              </pre>
            </div>
          )}

          {/* Metadata */}
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
            <span>
              Session:{" "}
              <Link href={`/traces/${event.session_id}`} className="text-primary-accent hover:underline font-[family-name:var(--font-mono)]">
                {event.session_id.slice(0, 12)}...
              </Link>
            </span>
            {event.agent_type && <span>Agent: {event.agent_type}</span>}
            {event.stop_reason && <span>Reason: {event.stop_reason}</span>}
            {event.user_id && <span>User: {event.user_id.slice(0, 8)}...</span>}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────── */

export default function ErrorsPage() {
  const { data: errors, isLoading, isError, error, refetch } = useOtelErrors();

  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<ErrorType | "all">("all");
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [debouncedSearch, setDebouncedSearch] = useState("");

  const handleSearch = useCallback((value: string) => {
    setSearch(value);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedSearch(value), 300);
  }, []);

  const filtered = useMemo(() => {
    if (!errors) return [];
    const q = debouncedSearch.toLowerCase();
    return errors.filter((e) => {
      if (typeFilter !== "all" && classifyError(e) !== typeFilter) return false;
      if (q) {
        const searchable = [e.tool_name, e.error, e.body, e.agent_type, e.session_id].join(" ").toLowerCase();
        if (!searchable.includes(q)) return false;
      }
      return true;
    });
  }, [errors, typeFilter, debouncedSearch]);

  // Counts by type
  const counts = useMemo(() => {
    if (!errors) return { tool_failure: 0, stop_failure: 0, api_error: 0 };
    const c = { tool_failure: 0, stop_failure: 0, api_error: 0 };
    for (const e of errors) c[classifyError(e)]++;
    return c;
  }, [errors]);

  return (
    <>
      <PageHeader
        title="Errors"
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Errors" },
        ]}
      />
      <div className="p-6 w-full mx-auto space-y-4">
        {isLoading ? (
          <TableSkeleton rows={6} cols={4} />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : (errors ?? []).length === 0 ? (
          <EmptyState
            icon={AlertTriangle}
            title="No errors"
            description="Error events from tool failures, API errors, and stop failures will appear here."
          />
        ) : (
          <div className="animate-in space-y-4">
            {/* Filters */}
            <div className="flex items-center gap-3 flex-wrap">
              <div className="relative max-w-sm flex-1">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Search errors, tools, sessions..."
                  value={search}
                  onChange={(e) => handleSearch(e.target.value)}
                  className="pl-8 h-8 text-sm"
                />
              </div>
              <div className="flex gap-1.5">
                {(["all", "tool_failure", "stop_failure", "api_error"] as const).map((t) => {
                  const active = typeFilter === t;
                  const count = t === "all" ? (errors?.length ?? 0) : counts[t];
                  const label = t === "all" ? "All" : errorTypeLabel(t);
                  return (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setTypeFilter(t)}
                      className={`px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors ${
                        active
                          ? "bg-foreground text-background border-foreground"
                          : "bg-muted/50 text-muted-foreground border-border hover:bg-muted"
                      }`}
                    >
                      {label} {count}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Error list */}
            <div className="space-y-2">
              {filtered.map((evt, i) => (
                <ErrorRow key={`${evt.timestamp}-${i}`} event={evt} />
              ))}
            </div>

            <p className="text-xs text-muted-foreground">
              {filtered.length} of {errors?.length ?? 0} error{(errors?.length ?? 0) !== 1 ? "s" : ""}
            </p>
          </div>
        )}
      </div>
    </>
  );
}
