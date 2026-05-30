// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface StatCardProps {
  label: string;
  value: string | number;
  trend?: number;
  subtitle?: string;
}

export function StatCard({ label, value, trend, subtitle }: StatCardProps) {
  return (
    <div className="rounded-lg border border-border p-4 space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl font-semibold font-[family-name:var(--font-display)] tabular-nums">
        {value}
      </p>
      <div className="flex items-center gap-1.5">
        {trend !== undefined && trend !== 0 && (
          <>
            {trend > 0 ? (
              <TrendingUp className="h-3 w-3 text-success" />
            ) : (
              <TrendingDown className="h-3 w-3 text-destructive" />
            )}
            <span
              className={`text-xs tabular-nums ${
                trend > 0 ? "text-success" : "text-destructive"
              }`}
            >
              {trend > 0 ? "+" : ""}
              {trend}%
            </span>
          </>
        )}
        {trend === 0 && <Minus className="h-3 w-3 text-muted-foreground" />}
        {subtitle && (
          <span className="text-xs text-muted-foreground">{subtitle}</span>
        )}
      </div>
    </div>
  );
}
