"use client";

import { useState, useMemo } from "react";
import { ScrollText, Download, Search, ChevronDown, ChevronRight } from "lucide-react";
import { useAuditLog } from "@/hooks/use-api";
import { admin } from "@/lib/api";
import type { AuditLogEntry } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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

const RESOURCE_TYPES = [
  "all", "user", "session", "agent", "mcp", "skill", "hook", "prompt",
  "sandbox", "listing", "alert", "eval", "feedback", "settings", "config",
  "trace", "diagnostics", "dashboard", "component_source", "cache",
];

const PAGE_SIZE = 50;

function formatTimestamp(ts: string) {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function actionColor(action: string): "default" | "secondary" | "destructive" | "outline" {
  if (action.includes("delete") || action.includes("reject")) return "destructive";
  if (action.includes("create") || action.includes("approve")) return "default";
  return "secondary";
}

function DetailRow({ entry }: { entry: AuditLogEntry }) {
  const [open, setOpen] = useState(false);
  const hasDetail = entry.detail && entry.detail !== "" && entry.detail !== "{}";

  return (
    <>
      <TableRow
        className="cursor-pointer hover:bg-muted/50"
        onClick={() => hasDetail && setOpen(!open)}
      >
        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
          {formatTimestamp(entry.timestamp)}
        </TableCell>
        <TableCell className="text-xs">{entry.actor_email || entry.actor_id}</TableCell>
        <TableCell>
          <Badge variant={actionColor(entry.action)} className="text-[10px]">
            {entry.action}
          </Badge>
        </TableCell>
        <TableCell className="text-xs">{entry.resource_type}</TableCell>
        <TableCell className="text-xs truncate max-w-[300px]" title={entry.resource_name || entry.resource_id}>
          {entry.resource_name || entry.resource_id || "-"}
        </TableCell>
        <TableCell className="text-xs text-muted-foreground">{entry.ip_address || "-"}</TableCell>
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
              <span className="text-muted-foreground">HTTP: </span>
              {entry.http_method} {entry.http_path}
              {entry.status_code ? ` (${entry.status_code})` : ""}
              <br />
              <span className="text-muted-foreground">User-Agent: </span>
              {entry.user_agent || "-"}
              <br />
              <span className="text-muted-foreground">Detail: </span>
              {entry.detail}
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

export default function AuditLogPage() {
  const { deploymentMode } = useDeploymentConfig();
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [resourceType, setResourceType] = useState("all");
  const [page, setPage] = useState(0);

  const filters = useMemo(() => {
    const f: Record<string, string> = {
      limit: String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    };
    if (actor.trim()) f.actor = actor.trim();
    if (action.trim()) f.action = action.trim();
    if (resourceType !== "all") f.resource_type = resourceType;
    return f;
  }, [actor, action, resourceType, page]);

  const { data, isLoading, isError, error, refetch } = useAuditLog(filters);

  const handleExport = async () => {
    const params: Record<string, string> = {};
    if (actor.trim()) params.actor = actor.trim();
    if (action.trim()) params.action = action.trim();
    if (resourceType !== "all") params.resource_type = resourceType;
    try {
      const csv = await admin.auditLogExport(params);
      const blob = new Blob([csv as unknown as string], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "audit_log.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // export failed silently
    }
  };

  if (deploymentMode !== "enterprise") {
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
            description="HIPAA-level audit logging is available in enterprise mode."
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
        {/* Filters */}
        <div className="flex flex-wrap gap-3 items-center">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Actor email..."
              value={actor}
              onChange={(e) => { setActor(e.target.value); setPage(0); }}
              className="pl-8 h-9 w-[200px] text-xs"
            />
          </div>
          <Input
            placeholder="Action (e.g. trace.view)..."
            value={action}
            onChange={(e) => { setAction(e.target.value); setPage(0); }}
            className="h-9 w-[200px] text-xs"
          />
          <Select value={resourceType} onValueChange={(v) => { setResourceType(v); setPage(0); }}>
            <SelectTrigger className="h-9 w-[160px] text-xs">
              <SelectValue placeholder="Resource type" />
            </SelectTrigger>
            <SelectContent>
              {RESOURCE_TYPES.map((t) => (
                <SelectItem key={t} value={t} className="text-xs">
                  {t === "all" ? "All types" : t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Table */}
        {isLoading ? (
          <TableSkeleton rows={10} cols={7} />
        ) : isError ? (
          <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} />
        ) : !data?.length ? (
          <EmptyState
            icon={ScrollText}
            title="No audit events"
            description="Events will appear here once actions are performed."
          />
        ) : (
          <>
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-xs w-[170px]">Timestamp</TableHead>
                    <TableHead className="text-xs">Actor</TableHead>
                    <TableHead className="text-xs">Action</TableHead>
                    <TableHead className="text-xs">Resource</TableHead>
                    <TableHead className="text-xs">Name / ID</TableHead>
                    <TableHead className="text-xs">IP</TableHead>
                    <TableHead className="text-xs w-8" />
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
                Showing {page * PAGE_SIZE + 1}–{page * PAGE_SIZE + data.length}
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
