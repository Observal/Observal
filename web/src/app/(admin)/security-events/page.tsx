"use client";

import { useState, useMemo } from "react";
import { ShieldAlert, Search, ChevronDown, ChevronRight } from "lucide-react";
import { useSecurityEvents } from "@/hooks/use-api";
import type { SecurityEvent } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";

const EVENT_TYPES = [
  "all",
  "auth.login.success",
  "auth.login.failure",
  "auth.sso.success",
  "authz.permission_denied",
  "authz.role_changed",
  "admin.user.created",
  "admin.user.deleted",
  "admin.setting.changed",
  "admin.alert_rule.changed",
  "agent.injection_detected",
  "agent.canary_parroted",
  "ingestion.secrets_redacted",
  "ingestion.malformed_otlp",
];

const SEVERITIES = ["all", "info", "warning", "critical"];
const PAGE_SIZE = 50;

function formatTimestamp(ts: string) {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function severityBadge(severity: string) {
  switch (severity) {
    case "critical":
      return <Badge variant="destructive" className="text-[10px]">{severity}</Badge>;
    case "warning":
      return <Badge className="text-[10px] bg-amber-500/15 text-amber-600 border-amber-500/20">{severity}</Badge>;
    default:
      return <Badge variant="secondary" className="text-[10px]">{severity}</Badge>;
  }
}

function outcomeBadge(outcome: string) {
  if (outcome === "failure") return <Badge variant="destructive" className="text-[10px]">{outcome}</Badge>;
  return <Badge variant="secondary" className="text-[10px]">{outcome}</Badge>;
}

function EventRow({ event }: { event: SecurityEvent }) {
  const [open, setOpen] = useState(false);
  const hasDetail = event.detail && event.detail !== "" && event.detail !== "{}";

  return (
    <>
      <TableRow
        className="cursor-pointer hover:bg-muted/50"
        onClick={() => hasDetail && setOpen(!open)}
      >
        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
          {formatTimestamp(event.timestamp)}
        </TableCell>
        <TableCell>
          <Badge variant="outline" className="text-[10px] font-mono">
            {event.event_type}
          </Badge>
        </TableCell>
        <TableCell>{severityBadge(event.severity)}</TableCell>
        <TableCell className="text-xs">{event.actor_email || event.actor_id || "-"}</TableCell>
        <TableCell className="text-xs">{event.target_type ? `${event.target_type}:${event.target_id}` : "-"}</TableCell>
        <TableCell>{outcomeBadge(event.outcome)}</TableCell>
        <TableCell className="text-xs">
          {hasDetail ? (
            open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />
          ) : null}
        </TableCell>
      </TableRow>
      {open && hasDetail && (
        <TableRow>
          <TableCell colSpan={7} className="bg-muted/30 px-6 py-3">
            <div className="text-xs font-mono whitespace-pre-wrap break-all">
              <span className="text-muted-foreground">IP: </span>{event.source_ip || "-"}
              <br />
              <span className="text-muted-foreground">User-Agent: </span>{event.user_agent || "-"}
              <br />
              <span className="text-muted-foreground">Detail: </span>{event.detail}
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

export default function SecurityEventsPage() {
  const { deploymentMode } = useDeploymentConfig();
  const [eventType, setEventType] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [actorEmail, setActorEmail] = useState("");
  const [page, setPage] = useState(0);

  const filters = useMemo(() => {
    const f: Record<string, string> = {
      limit: String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    };
    if (eventType !== "all") f.event_type = eventType;
    if (severity !== "all") f.severity = severity;
    if (actorEmail.trim()) f.actor_email = actorEmail.trim();
    return f;
  }, [eventType, severity, actorEmail, page]);

  const { data, isLoading, isError, error, refetch } = useSecurityEvents(filters);

  if (deploymentMode !== "enterprise") {
    return (
      <>
        <PageHeader
          title="Security Events"
          breadcrumbs={[{ label: "Admin" }, { label: "Security" }]}
        />
        <div className="p-6 w-full mx-auto">
          <EmptyState
            icon={ShieldAlert}
            title="Enterprise feature"
            description="Security event monitoring is available in enterprise mode."
          />
        </div>
      </>
    );
  }

  const events = data?.events ?? [];

  return (
    <>
      <PageHeader
        title="Security Events"
        breadcrumbs={[{ label: "Admin" }, { label: "Security" }]}
      />
      <div className="p-6 w-full mx-auto space-y-4">
        {/* Filters */}
        <div className="flex flex-wrap gap-3 items-center">
          <Select value={eventType} onValueChange={(v) => { setEventType(v); setPage(0); }}>
            <SelectTrigger className="h-9 w-[220px] text-xs">
              <SelectValue placeholder="Event type" />
            </SelectTrigger>
            <SelectContent>
              {EVENT_TYPES.map((t) => (
                <SelectItem key={t} value={t} className="text-xs">
                  {t === "all" ? "All event types" : t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={severity} onValueChange={(v) => { setSeverity(v); setPage(0); }}>
            <SelectTrigger className="h-9 w-[140px] text-xs">
              <SelectValue placeholder="Severity" />
            </SelectTrigger>
            <SelectContent>
              {SEVERITIES.map((s) => (
                <SelectItem key={s} value={s} className="text-xs">
                  {s === "all" ? "All severities" : s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Actor email..."
              value={actorEmail}
              onChange={(e) => { setActorEmail(e.target.value); setPage(0); }}
              className="pl-8 h-9 w-[200px] text-xs"
            />
          </div>
        </div>

        {/* Table */}
        {isLoading ? (
          <TableSkeleton rows={10} cols={7} />
        ) : isError ? (
          <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} />
        ) : !events.length ? (
          <EmptyState
            icon={ShieldAlert}
            title="No security events"
            description="Security events will appear here when they occur."
          />
        ) : (
          <>
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-xs w-[170px]">Timestamp</TableHead>
                    <TableHead className="text-xs">Event Type</TableHead>
                    <TableHead className="text-xs w-[90px]">Severity</TableHead>
                    <TableHead className="text-xs">Actor</TableHead>
                    <TableHead className="text-xs">Target</TableHead>
                    <TableHead className="text-xs w-[80px]">Outcome</TableHead>
                    <TableHead className="text-xs w-8" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {events.map((event) => (
                    <EventRow key={event.event_id} event={event} />
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">
                Showing {page * PAGE_SIZE + 1}–{page * PAGE_SIZE + events.length}
                {data?.total ? ` of ${data.total}` : ""}
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <Button variant="outline" size="sm" disabled={events.length < PAGE_SIZE} onClick={() => setPage(page + 1)}>
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
