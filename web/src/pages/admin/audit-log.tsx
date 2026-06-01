// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState, useMemo, useCallback, useRef } from "react";
import { useSearch, useLocation } from "@tanstack/react-router";
import {
  ScrollText,
  Download,
  Search,
  ChevronDown,
  ChevronRight,
  Shield,
  Clock,
  AlertTriangle,
} from "lucide-react";
import { useAuditLog } from "@/hooks/use-api";
import { admin } from "@/lib/api";
import type { AuditLogEntry } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";

const PAGE_SIZE = 50;

// Parse Discord-style search: actor:admin@x.com outcome:denied sensitivity:high
// Supports quoted values: actor:"John Doe" action:"agent.pull"
function parseSearchQuery(query: string): Record<string, string> {
  const params: Record<string, string> = {};
  const tokens = query.match(/(\w+):(?:"([^"]*)"|([^\s]*))/g);
  if (tokens) {
    for (const token of tokens) {
      const colonIdx = token.indexOf(":");
      const key = token.slice(0, colonIdx);
      let value = token.slice(colonIdx + 1);
      // Strip quotes
      if (value.startsWith('"') && value.endsWith('"')) {
        value = value.slice(1, -1);
      }
      const keyMap: Record<string, string> = {
        actor: "actor",
        action: "action",
        type: "resource_type",
        resource: "resource_type",
        outcome: "outcome",
        sensitivity: "sensitivity",
        source: "source",
        method: "http_method",
        ip: "ip_address",
      };
      const apiKey = keyMap[key.toLowerCase()];
      if (apiKey) params[apiKey] = value;
    }
  }
  return params;
}

function formatTimestamp(ts: string) {
  try {
    // ClickHouse returns "YYYY-MM-DD HH:MM:SS.mmm" without timezone
    const d = new Date(ts + "Z");
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return ts;
  }
}

function outcomeBadge(outcome: string) {
  switch (outcome) {
    case "success":
      return <Badge variant="default" className="text-[10px] bg-success/20 text-success border-success/30">{outcome}</Badge>;
    case "denied":
      return <Badge variant="destructive" className="text-[10px]">{outcome}</Badge>;
    case "error":
      return <Badge variant="destructive" className="text-[10px]">{outcome}</Badge>;
    case "not_found":
      return <Badge variant="outline" className="text-[10px]">{outcome}</Badge>;
    default:
      return <Badge variant="secondary" className="text-[10px]">{outcome || "unknown"}</Badge>;
  }
}

function sensitivityBadge(level: string) {
  switch (level) {
    case "phi_adjacent":
      return <Badge variant="destructive" className="text-[10px]">PHI</Badge>;
    case "admin":
      return <Badge className="text-[10px] bg-warning/20 text-warning border-warning/30">admin</Badge>;
    case "high":
      return <Badge className="text-[10px] bg-info/20 text-info border-info/30">high</Badge>;
    case "standard":
      return <Badge variant="secondary" className="text-[10px]">std</Badge>;
    case "low":
      return <Badge variant="outline" className="text-[10px]">low</Badge>;
    default:
      return <Badge variant="outline" className="text-[10px]">{level}</Badge>;
  }
}

function DetailRow({ entry }: { entry: AuditLogEntry }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <TableRow
        className="cursor-pointer hover:bg-muted/50 text-xs"
        onClick={() => setOpen(!open)}
      >
        <TableCell className="text-muted-foreground whitespace-nowrap font-mono text-[11px]">
          {formatTimestamp(entry.timestamp)}
        </TableCell>
        <TableCell className="max-w-[140px] truncate">
          {entry.actor_email || <span className="text-muted-foreground italic">anonymous</span>}
        </TableCell>
        <TableCell>
          <code className="text-[11px] bg-muted px-1 py-0.5 rounded">{entry.action}</code>
        </TableCell>
        <TableCell>{outcomeBadge(entry.outcome)}</TableCell>
        <TableCell>{sensitivityBadge(entry.sensitivity)}</TableCell>
        <TableCell className="text-muted-foreground font-mono text-[11px]">
          {entry.status_code}
        </TableCell>
        <TableCell className="text-muted-foreground font-mono text-[11px]">
          {entry.duration_ms > 0 ? `${entry.duration_ms.toFixed(0)}ms` : "-"}
        </TableCell>
        <TableCell className="text-muted-foreground text-[11px]">
          {entry.ip_address || "-"}
        </TableCell>
        <TableCell>
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </TableCell>
      </TableRow>
      {open && (
        <TableRow>
          <TableCell colSpan={9} className="bg-muted/30 px-6 py-3">
            <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-xs font-mono">
              <div><span className="text-muted-foreground">Event ID: </span>{entry.event_id}</div>
              <div><span className="text-muted-foreground">Request ID: </span>{entry.request_id || "-"}</div>
              <div><span className="text-muted-foreground">HTTP: </span>{entry.http_method} {entry.http_path}</div>
              <div><span className="text-muted-foreground">Actor ID: </span>{entry.actor_id}</div>
              <div><span className="text-muted-foreground">Role: </span>{entry.actor_role}</div>
              <div><span className="text-muted-foreground">Org: </span>{entry.org_id || "-"}</div>
              <div><span className="text-muted-foreground">Resource: </span>{entry.resource_type} {entry.resource_id ? `(${entry.resource_id})` : ""}</div>
              <div><span className="text-muted-foreground">Source: </span>{entry.source}</div>
              <div className="col-span-2"><span className="text-muted-foreground">User-Agent: </span>{entry.user_agent || "-"}</div>
              {entry.detail && <div className="col-span-2"><span className="text-muted-foreground">Detail: </span>{entry.detail}</div>}
              <div className="col-span-2 mt-1 pt-1 border-t border-border">
                <span className="text-muted-foreground">Chain Hash: </span>
                <span className="text-[10px] break-all">{entry.chain_hash || "-"}</span>
              </div>
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

export default function AuditLogPage() {
  const { licensedFeatures } = useDeploymentConfig();
  const { search: searchParam } = useSearch({ from: "/_authed/_admin/audit-log" });
  const { pathname } = useLocation();
  const [searchQuery, setSearchQuery] = useState(searchParam ?? "");
  const [page, setPage] = useState(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const updateURL = useCallback(
    (value: string) => {
      const params = new URLSearchParams(window.location.search);
      if (value) {
        params.set("search", value);
      } else {
        params.delete("search");
      }
      const qs = params.toString();
      window.history.replaceState(null, "", qs ? `${pathname}?${qs}` : pathname);
    },
    [pathname],
  );

  const handleSearchChange = useCallback(
    (value: string) => {
      setSearchQuery(value);
      setPage(0);
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => updateURL(value), 300);
    },
    [updateURL],
  );

  const filters = useMemo(() => {
    const parsed = parseSearchQuery(searchQuery);
    return {
      ...parsed,
      limit: String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    };
  }, [searchQuery, page]);

  const { data, isLoading, isError, error, refetch } = useAuditLog(filters);

  const handleExport = useCallback(async () => {
    const parsed = parseSearchQuery(searchQuery);
    try {
      const csv = await admin.auditLogExport(parsed);
      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "hipaa_audit_trail.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // export failed
    }
  }, [searchQuery]);

  if (!licensedFeatures.includes("audit") && !licensedFeatures.includes("all")) {
    return (
      <>
        <PageHeader
          title="Audit Log"
          breadcrumbs={[{ label: "Admin" }, { label: "Audit Log" }]}
        />
        <div className="p-6 w-full mx-auto">
          <EmptyState
            icon={ScrollText}
            title="Enterprise feature"
            description="HIPAA-level audit logging requires the audit license feature."
          />
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Audit Log"
        breadcrumbs={[{ label: "Admin" }, { label: "Audit Log" }]}
        actionButtonsRight={
          <Button variant="outline" size="sm" onClick={handleExport}>
            <Download className="h-3.5 w-3.5 mr-1.5" />
            Export CSV
          </Button>
        }
      />
      <div className="p-6 w-full mx-auto space-y-4">
        {/* Search */}
        <div className="space-y-2">
          <div className="relative">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search: actor:email action:login outcome:denied sensitivity:phi_adjacent source:cli"
              value={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="pl-9 h-9 text-xs font-mono"
            />
          </div>
          <div className="flex gap-1.5 flex-wrap">
            <span className="text-[10px] text-muted-foreground">Filters:</span>
            {["actor:", "action:", "outcome:", "sensitivity:", "source:", "type:", "ip:"].map((hint) => (
              <button
                key={hint}
                className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground hover:text-foreground hover:bg-muted/80 font-mono transition-colors"
                onClick={() => handleSearchChange(searchQuery + (searchQuery && !searchQuery.endsWith(" ") ? " " : "") + hint)}
              >
                {hint}
              </button>
            ))}
          </div>
        </div>

        {/* Stats bar */}
        {data && data.length > 0 && (
          <div className="flex gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {data.length} events
            </span>
            <span className="flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" />
              {data.filter((e) => e.outcome === "denied").length} denied
            </span>
            <span className="flex items-center gap-1">
              <Shield className="h-3 w-3" />
              {data.filter((e) => e.sensitivity === "phi_adjacent").length} PHI-adjacent
            </span>
          </div>
        )}

        {/* Table */}
        {isLoading ? (
          <TableSkeleton rows={10} cols={9} />
        ) : isError ? (
          <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} />
        ) : !data?.length ? (
          <EmptyState
            icon={ScrollText}
            title="No audit events"
            description="Events will appear here as API requests are made."
          />
        ) : (
          <>
            <div className="rounded-md border overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-[11px] w-[130px]">Time</TableHead>
                    <TableHead className="text-[11px]">Actor</TableHead>
                    <TableHead className="text-[11px]">Action</TableHead>
                    <TableHead className="text-[11px]">Outcome</TableHead>
                    <TableHead className="text-[11px]">Sensitivity</TableHead>
                    <TableHead className="text-[11px] w-[50px]">Status</TableHead>
                    <TableHead className="text-[11px] w-[60px]">Latency</TableHead>
                    <TableHead className="text-[11px]">IP</TableHead>
                    <TableHead className="text-[11px] w-8" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.map((entry) => (
                    <DetailRow key={entry.event_id} entry={entry} />
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">
                Page {page + 1} ({data.length} results)
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage(page - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={data.length < PAGE_SIZE}
                  onClick={() => setPage(page + 1)}
                >
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
