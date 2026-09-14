// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import {
  AlertTriangle,
  BookOpen,
  Building2,
  CheckCircle2,
  Database,
  KeyRound,
  RefreshCw,
  XCircle,
} from "lucide-react";

import { PageHeader, PageIntro } from "@/components/layouts/page-header";
import { ErrorState } from "@/components/shared/error-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useDiagnostics } from "@/hooks/use-api";
import { cn } from "@/lib/utils";
import { AdminMetric, AdminMetricStrip, AdminPanel } from "./components/admin-surface";

function StatusIcon({ status, className }: { status: string; className?: string }) {
  if (status === "ok") return <CheckCircle2 className={cn("text-success", className)} />;
  if (["degraded", "misconfigured", "missing"].includes(status)) {
    return <AlertTriangle className={cn("text-warning", className)} />;
  }
  return <XCircle className={cn("text-destructive", className)} />;
}

function StatusBadge({ status }: { status: string }) {
  const classes = status === "ok"
    ? "border-success/20 bg-success/12 text-success"
    : ["degraded", "misconfigured", "missing"].includes(status)
      ? "border-warning/20 bg-warning/12 text-warning"
      : status === "disabled"
        ? "border-border bg-surface-raised text-muted-foreground"
        : "border-destructive/20 bg-destructive/12 text-destructive";

  return (
    <Badge variant="outline" className={cn("gap-1.5 text-2xs font-medium", classes)}>
      {status === "disabled"
        ? <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />
        : <StatusIcon status={status} className="h-3 w-3" />}
      {status}
    </Badge>
  );
}

function CheckPanel({
  icon,
  title,
  status,
  children,
  className,
}: {
  icon: ReactNode;
  title: string;
  status: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <AdminPanel
      className={className}
      title={
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="text-muted-foreground [&_svg]:h-4 [&_svg]:w-4">{icon}</span>
          {title}
        </span>
      }
      action={<StatusBadge status={status} />}
      contentClassName="px-5 py-4"
    >
      {children}
    </AdminPanel>
  );
}

function DataRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-6 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums text-foreground">{value}</span>
    </div>
  );
}

export default function DiagnosticsPage() {
  const { data, isLoading, isError, error, refetch, dataUpdatedAt } = useDiagnostics();

  return (
    <>
      <PageHeader
        title="Diagnostics"
        breadcrumbs={[{ label: "Administration" }, { label: "Diagnostics" }]}
      />
      <div className="page-body mx-auto w-full">
        <PageIntro
          eyebrow="System health"
          title="Diagnostics"
          subtitle="Inspect storage, signing keys, runtime configuration, and supporting services."
        >
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isLoading}>
            <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
            Refresh
          </Button>
        </PageIntro>

        {isError ? (
          <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} />
        ) : isLoading && !data ? (
          <div className="space-y-5" aria-label="Loading diagnostics">
            <div className="grid grid-cols-1 gap-px overflow-hidden rounded-xl bg-border sm:grid-cols-2 xl:grid-cols-4">
              {[1, 2, 3, 4].map((i) => <div key={i} className="h-28 animate-pulse bg-card" />)}
            </div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {[1, 2, 3, 4].map((i) => <div key={i} className="h-36 animate-pulse rounded-xl bg-card" />)}
            </div>
          </div>
        ) : data ? (
          <div className="space-y-5">
            <AdminMetricStrip>
              <AdminMetric
                label="System status"
                value={data.status === "ok" ? "Operational" : data.status}
                detail={dataUpdatedAt ? `Updated ${new Date(dataUpdatedAt).toLocaleTimeString()}` : "Not yet refreshed"}
                icon={<StatusIcon status={data.status} />}
                tone={data.status === "ok" ? "success" : "warning"}
              />
              <AdminMetric
                label="Database"
                value={data.checks.database?.status === "ok" ? "Healthy" : String(data.checks.database?.status ?? "Unknown")}
                detail={data.checks.database?.users !== undefined ? `${String(data.checks.database.users)} users` : "Connection check"}
                icon={<Database />}
                tone={data.checks.database?.status === "ok" ? "success" : "warning"}
              />
              <AdminMetric
                label="Signing keys"
                value={data.checks.jwt_keys?.status === "ok" ? "Ready" : String(data.checks.jwt_keys?.status ?? "Unknown")}
                detail={data.checks.jwt_keys?.algorithm ? String(data.checks.jwt_keys.algorithm) : "JWT configuration"}
                icon={<KeyRound />}
                tone={data.checks.jwt_keys?.status === "ok" ? "success" : "warning"}
              />
              <AdminMetric
                label="Runtime config"
                value={data.checks.runtime_config?.status === "ok" ? "Valid" : String(data.checks.runtime_config?.status ?? "Unknown")}
                detail={Array.isArray(data.checks.runtime_config?.issues) ? `${data.checks.runtime_config.issues.length} issues` : "Configuration check"}
                icon={<Building2 />}
                tone={data.checks.runtime_config?.status === "ok" ? "success" : "warning"}
              />
            </AdminMetricStrip>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {data.checks.database && (
                <CheckPanel icon={<Database />} title="Database" status={String(data.checks.database.status)}>
                  <div className="space-y-2.5">
                    {data.checks.database.users !== undefined && <DataRow label="Users" value={String(data.checks.database.users)} />}
                    {data.checks.database.demo_accounts !== undefined && <DataRow label="Demo accounts" value={String(data.checks.database.demo_accounts)} />}
                    {data.checks.database.detail ? <p className="pt-2 text-xs text-destructive">{String(data.checks.database.detail)}</p> : null}
                  </div>
                </CheckPanel>
              )}

              {data.checks.jwt_keys && (
                <CheckPanel icon={<KeyRound />} title="JWT keys" status={String(data.checks.jwt_keys.status)}>
                  <DataRow label="Algorithm" value={<span className="font-mono">{String(data.checks.jwt_keys.algorithm)}</span>} />
                </CheckPanel>
              )}

              <CheckPanel icon={<BookOpen />} title="Model catalog" status="disabled">
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Disabled while the Insights model picker moves to the LiteLLM catalog.
                </p>
              </CheckPanel>

              {data.checks.runtime_config && (
                <CheckPanel icon={<Building2 />} title="Runtime config" status={String(data.checks.runtime_config.status)}>
                  {Array.isArray(data.checks.runtime_config.issues) && data.checks.runtime_config.issues.length > 0 ? (
                    <ul className="space-y-2.5">
                      {(data.checks.runtime_config.issues as string[]).map((issue) => (
                        <li key={issue} className="flex items-start gap-2 text-xs">
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
                          <span>{issue}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted-foreground">No configuration issues detected.</p>
                  )}
                </CheckPanel>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}
