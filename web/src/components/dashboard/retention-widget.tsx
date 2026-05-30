// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Database } from "lucide-react";
import { useRetentionStats } from "@/hooks/use-api";
import { hasMinRole } from "@/hooks/use-role-guard";
import { getUserRole } from "@/lib/api";
import { DashboardCard } from "./dashboard-card";

export function RetentionWidget() {
  const { data, isLoading } = useRetentionStats();

  if (!hasMinRole(getUserRole(), "admin")) return null;
  if (!isLoading && !data?.retention_enabled) return null;

  return (
    <DashboardCard
      title={
        <span className="flex items-center gap-1.5">
          <Database className="h-4 w-4" />
          Data Retention
        </span>
      }
      isLoading={isLoading}
    >
      {data && (
        <div className="space-y-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            <span className="text-muted-foreground">Active</span>
          </div>

          <div className="text-xs text-muted-foreground">
            {data.data_retention_days ?? "—"} days traces / {data.score_retention_days || (data.data_retention_days ? data.data_retention_days * 2 : "—")} days scores & insights
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="rounded bg-muted/50 p-2">
              <p className="text-[10px] text-muted-foreground uppercase">Total Traces</p>
              <p className="text-sm font-medium">{(data.total_traces ?? 0).toLocaleString()}</p>
            </div>
            <div className="rounded bg-muted/50 p-2">
              <p className="text-[10px] text-muted-foreground uppercase">Oldest</p>
              <p className="text-sm font-medium">{data.oldest_trace_age_days ?? 0}d</p>
            </div>
          </div>

          {(data.traces_expiring_7d ?? 0) > 0 && (
            <div className="rounded bg-amber-500/10 border border-amber-500/20 p-2">
              <p className="text-xs text-amber-700 dark:text-amber-400 font-medium">
                {data.traces_expiring_7d.toLocaleString()} traces expiring within 7 days
              </p>
            </div>
          )}

          <p className="text-[10px] text-muted-foreground">
            Purge schedule: {data.next_purge_approx ?? "Not scheduled"}
          </p>
        </div>
      )}
    </DashboardCard>
  );
}
