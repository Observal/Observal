"use client";

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
    <div className={cn("overflow-hidden rounded-lg border bg-card px-4 py-4 shadow-xs", className)}>
      <dt className="truncate text-xs font-medium text-muted-foreground">{title}</dt>
      <dd className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tracking-tight">{value}</span>
        {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground" />}
      </dd>
      {(description || trend) && (
        <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
          {trend && (
            <span className={cn("inline-flex items-center gap-0.5 font-medium", trend.positive ? "text-dark-green" : "text-dark-red")}>
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
