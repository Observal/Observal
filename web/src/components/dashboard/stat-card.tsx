// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0


import type { LucideIcon } from "lucide-react";
import { TrendingUp, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatCardProps {
  title: string;
  value: string | number;
  description?: string;
  icon?: LucideIcon;
  trend?: { value: number; positive: boolean };
  className?: string;
}

export function StatCard({ title, value, description, icon: Icon, trend, className }: StatCardProps) {
  return (
    <div className={cn("overflow-hidden bg-card px-5 py-5", className)}>
      <dt className="truncate text-xs text-muted-foreground">{title}</dt>
      <dd className="mt-2 flex items-baseline gap-2">
        {/* Metric values are bold, tightly tracked, and tabular so columns of
            figures stay aligned as values change. */}
        <span className="text-2xl font-bold tabular-nums tracking-[-0.02em]">{value}</span>
        {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground" />}
      </dd>
      {(description || trend) && (
        <div className="mt-1 flex items-center gap-1.5 text-2xs text-muted-foreground">
          {trend && (
            <span className={cn("inline-flex items-center gap-0.5 font-semibold", trend.positive ? "text-success" : "text-destructive")}>
              {trend.positive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
              {trend.value}%
            </span>
          )}
          {description && <span>{description}</span>}
        </div>
      )}
    </div>
  );
}
