// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0


import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface StatCardProps {
  label: string;
  value: string | number;
  trend?: number;
  subtitle?: string;
}

export function StatCard({ label, value, trend, subtitle }: StatCardProps) {
  return (
    <div className="min-w-0 bg-card px-5 py-4">
      <p className="text-2xs text-muted-foreground">{label}</p>
      <p className="mt-3 text-2xl font-semibold tracking-[-0.025em] tabular-nums">
        {value}
      </p>
      <div className="mt-1 flex items-center gap-1.5">
        {trend !== undefined && trend !== 0 && (
          <>
            {trend > 0 ? (
              <TrendingUp className="h-3 w-3 text-success" />
            ) : (
              <TrendingDown className="h-3 w-3 text-destructive" />
            )}
            <span
              className={`text-2xs font-semibold tabular-nums ${
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
          <span className="text-2xs text-muted-foreground">{subtitle}</span>
        )}
      </div>
    </div>
  );
}
