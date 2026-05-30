// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { CheckCircle2, AlertTriangle, XCircle, RefreshCw, Database, KeyRound, Building2, BookOpen } from "lucide-react";
import { useDiagnostics, useModels, useRefreshModels } from "@/hooks/use-api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/layouts/page-header";
import { ErrorState } from "@/components/shared/error-state";

function StatusIcon({ status }: { status: string }) {
  if (status === "ok") return <CheckCircle2 className="h-5 w-5 text-success" />;
  if (status === "degraded" || status === "misconfigured" || status === "missing")
    return <AlertTriangle className="h-5 w-5 text-warning" />;
  return <XCircle className="h-5 w-5 text-red-500" />;
}

function statusBadge(status: string) {
  switch (status) {
    case "ok":
      return <Badge className="bg-success/15 text-success border-success/20">{status}</Badge>;
    case "degraded":
    case "misconfigured":
    case "missing":
      return <Badge className="bg-warning/15 text-warning border-warning/20">{status}</Badge>;
    default:
      return <Badge variant="destructive">{status}</Badge>;
  }
}

function CatalogStatusCard() {
  const { data, isLoading, isError, error } = useModels();
  const refresh = useRefreshModels();

  let badgeStatus = "ok";
  if (isError) badgeStatus = "error";
  else if (data?.degraded) badgeStatus = "degraded";

  return (
    <Card className="md:col-span-2">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-sm">Model Catalog</CardTitle>
          <div className="ml-auto flex items-center gap-2">
            {statusBadge(badgeStatus)}
            <Button
              variant="outline"
              size="sm"
              disabled={refresh.isPending || isLoading}
              onClick={() => refresh.mutate()}
            >
              <RefreshCw
                className={`h-3.5 w-3.5 mr-1.5 ${refresh.isPending ? "animate-spin" : ""}`}
              />
              Refresh now
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {isError ? (
          <p className="text-xs text-destructive">{(error as Error)?.message}</p>
        ) : (
          <>
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">Source</span>
              <span className="font-mono font-medium">{data?.source ?? "—"}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">Models</span>
              <span className="font-medium">{data?.model_count ?? 0}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">Fetched at</span>
              <span className="font-medium">
                {data?.fetched_at ? new Date(data.fetched_at).toLocaleString() : "—"}
              </span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">Degraded</span>
              <span className="font-medium">{data?.degraded ? "yes" : "no"}</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}


export default function DiagnosticsPage() {
  const { data, isLoading, isError, error, refetch, dataUpdatedAt } = useDiagnostics();

  return (
    <>
      <PageHeader
        title="Diagnostics"
        breadcrumbs={[{ label: "Admin" }, { label: "Diagnostics" }]}
        actionButtonsRight={
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isLoading}>
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        }
      />
      <div className="p-6 w-full mx-auto space-y-6">
        {isError ? (
          <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} />
        ) : isLoading && !data ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <Card key={i} className="animate-pulse">
                <CardHeader className="pb-3">
                  <div className="h-5 w-32 bg-muted rounded" />
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    <div className="h-4 w-48 bg-muted rounded" />
                    <div className="h-4 w-36 bg-muted rounded" />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : data ? (
          <>
            {/* Overall status */}
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <StatusIcon status={data.status} />
                    <div>
                      <CardTitle className="text-lg">System Status</CardTitle>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        License: {data.licensed ? "Enterprise" : "Community"}
                        {dataUpdatedAt ? ` · Updated ${new Date(dataUpdatedAt).toLocaleTimeString()}` : ""}
                      </p>
                    </div>
                  </div>
                  {statusBadge(data.status)}
                </div>
              </CardHeader>
            </Card>

            {/* Check cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Database */}
              {data.checks.database && (
                <Card>
                  <CardHeader className="pb-3">
                    <div className="flex items-center gap-2">
                      <Database className="h-4 w-4 text-muted-foreground" />
                      <CardTitle className="text-sm">Database</CardTitle>
                      <div className="ml-auto">{statusBadge(data.checks.database.status as string)}</div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-1.5">
                    {data.checks.database.users !== undefined && (
                      <div className="flex justify-between text-xs">
                        <span className="text-muted-foreground">Users</span>
                        <span className="font-medium">{String(data.checks.database.users)}</span>
                      </div>
                    )}
                    {data.checks.database.demo_accounts !== undefined && (
                      <div className="flex justify-between text-xs">
                        <span className="text-muted-foreground">Demo accounts</span>
                        <span className="font-medium">{String(data.checks.database.demo_accounts)}</span>
                      </div>
                    )}
                    {data.checks.database.detail ? (
                      <p className="text-xs text-destructive mt-2">{String(data.checks.database.detail)}</p>
                    ) : null}
                  </CardContent>
                </Card>
              )}

              {/* JWT Keys */}
              {data.checks.jwt_keys && (
                <Card>
                  <CardHeader className="pb-3">
                    <div className="flex items-center gap-2">
                      <KeyRound className="h-4 w-4 text-muted-foreground" />
                      <CardTitle className="text-sm">JWT Keys</CardTitle>
                      <div className="ml-auto">{statusBadge(data.checks.jwt_keys.status as string)}</div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground">Algorithm</span>
                      <span className="font-mono font-medium">{String(data.checks.jwt_keys.algorithm)}</span>
                    </div>
                  </CardContent>
                </Card>
              )}

              <CatalogStatusCard />

              {/* Enterprise */}
              {data.checks.enterprise && (
                <Card className="md:col-span-2">
                  <CardHeader className="pb-3">
                    <div className="flex items-center gap-2">
                      <Building2 className="h-4 w-4 text-muted-foreground" />
                      <CardTitle className="text-sm">Enterprise Config</CardTitle>
                      <div className="ml-auto">{statusBadge(data.checks.enterprise.status as string)}</div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {Array.isArray(data.checks.enterprise.issues) && data.checks.enterprise.issues.length > 0 ? (
                      <ul className="space-y-1.5">
                        {(data.checks.enterprise.issues as string[]).map((issue: string, i: number) => (
                          <li key={i} className="flex items-start gap-2 text-xs">
                            <AlertTriangle className="h-3.5 w-3.5 text-warning mt-0.5 shrink-0" />
                            <span>{issue}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-muted-foreground">No configuration issues detected.</p>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}
