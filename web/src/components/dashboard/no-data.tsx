// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

interface NoDataProps {
  isLoading?: boolean;
  noDataText?: string;
  description?: string;
  className?: string;
  children?: React.ReactNode;
}

export function NoData({
  isLoading = false,
  noDataText = "No data",
  description,
  className,
  children,
}: NoDataProps) {
  if (isLoading) {
    return (
      <div className={cn("min-h-36 w-full rounded-md", className)}>
        <Skeleton className="h-36 w-full" />
      </div>
    );
  }

  return (
    <div className={cn("flex min-h-36 w-full items-center justify-center rounded-md border border-dashed", className)}>
      <div className="text-center">
        <p className="text-sm text-muted-foreground">{noDataText}</p>
        {description && <p className="mt-1 text-xs text-muted-foreground/70">{description}</p>}
        {children}
      </div>
    </div>
  );
}
