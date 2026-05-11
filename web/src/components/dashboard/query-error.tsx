// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface QueryErrorProps {
  message?: string;
  onRetry?: () => void;
}

export function QueryError({ message, onRetry }: QueryErrorProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-destructive/30 py-12">
      <AlertCircle className="h-8 w-8 text-destructive/60" />
      <p className="mt-3 text-sm font-medium">Something went wrong</p>
      <p className="mt-1 max-w-sm text-center text-xs text-muted-foreground">
        {message ?? "Failed to load data. Check your connection and try again."}
      </p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
          <RefreshCw className="mr-1 h-3 w-3" /> Retry
        </Button>
      )}
    </div>
  );
}
