"use client";

import { use, useState, useCallback } from "react";
import { useOtelSession } from "@/hooks/use-api";
import { FileText, ChevronDown, ChevronRight, ChevronsUpDown } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { DetailSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";

function colorizeJson(raw: string): React.ReactNode {
  const lines = raw.split("\n");
  return lines.map((line, i) => {
    const colonIdx = line.indexOf(":");
    if (colonIdx === -1) {
      return (
        <span key={i}>
          {line}
          {i < lines.length - 1 ? "\n" : ""}
        </span>
      );
    }
    const key = line.slice(0, colonIdx);
    const value = line.slice(colonIdx);
    return (
      <span key={i}>
        <span className="text-muted-foreground">{key}</span>
        <span className="text-foreground">{value}</span>
        {i < lines.length - 1 ? "\n" : ""}
      </span>
    );
  });
}

function EventRow({
  event,
  isExpanded,
  onToggle,
}: {
  event: any;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-2 w-full text-left py-2 px-3 rounded-md hover:bg-muted/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/20"
      >
        {isExpanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        )}
        <span className="text-sm font-medium truncate">{event.event_name}</span>
        {event.timestamp && (
          <span className="ml-auto text-xs text-muted-foreground tabular-nums shrink-0">
            {new Date(event.timestamp).toLocaleTimeString()}
          </span>
        )}
      </button>
      {isExpanded && event.body && (
        <div className="ml-6 mr-3 mb-2 mt-1">
          <pre className="text-xs font-[family-name:var(--font-mono)] leading-relaxed whitespace-pre-wrap bg-surface-sunken rounded-md p-3 overflow-x-auto">
            {colorizeJson(event.body)}
          </pre>
        </div>
      )}
    </div>
  );
}

export default function TraceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, isLoading, isError, error, refetch } = useOtelSession(id);

  const session = data as any;
  const events: any[] = session?.events ?? [];

  const [expandedSet, setExpandedSet] = useState<Set<number>>(new Set());

  const toggleEvent = useCallback((index: number) => {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setExpandedSet((prev) => {
      if (prev.size === events.length) {
        return new Set();
      }
      return new Set(events.map((_, i) => i));
    });
  }, [events.length]);

  const allExpanded = expandedSet.size === events.length && events.length > 0;

  return (
    <>
      <PageHeader
        title={isLoading ? "Trace" : id.slice(0, 16) + "..."}
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Traces", href: "/traces" },
          { label: id.slice(0, 12) + "..." },
        ]}
      />
      <div className="p-6 max-w-6xl mx-auto space-y-6">
        {isLoading ? (
          <DetailSkeleton />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : !data ? (
          <ErrorState message="Trace not found" />
        ) : (
          <>
            {/* Header info */}
            <div className="animate-in flex flex-wrap items-center gap-x-6 gap-y-2">
              <div>
                <span className="text-xs text-muted-foreground block mb-0.5">Session ID</span>
                <span className="text-sm font-[family-name:var(--font-mono)]">{id}</span>
              </div>
              {session.service_name && (
                <div>
                  <span className="text-xs text-muted-foreground block mb-0.5">Service</span>
                  <span className="text-sm">{session.service_name}</span>
                </div>
              )}
              {events.length > 0 && events[0]?.timestamp && (
                <div>
                  <span className="text-xs text-muted-foreground block mb-0.5">First Event</span>
                  <span className="text-sm tabular-nums">{new Date(events[0].timestamp).toLocaleString()}</span>
                </div>
              )}
            </div>

            <Separator />

            {/* Events */}
            {events.length === 0 ? (
              <EmptyState
                icon={FileText}
                title="No events in this trace"
                description="Events will appear here once spans are recorded for this session."
              />
            ) : (
              <div className="animate-in stagger-1 space-y-1">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-muted-foreground">
                    {events.length} event{events.length !== 1 ? "s" : ""}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={toggleAll}
                    className="h-7 text-xs gap-1"
                  >
                    <ChevronsUpDown className="h-3 w-3" />
                    {allExpanded ? "Collapse all" : "Expand all"}
                  </Button>
                </div>
                {events.map((evt: any, i: number) => (
                  <div key={i}>
                    <EventRow
                      event={evt}
                      isExpanded={expandedSet.has(i)}
                      onToggle={() => toggleEvent(i)}
                    />
                    {i < events.length - 1 && <Separator className="my-0" />}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
