// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { AlertCircle, LogIn, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  const isSessionExpired =
    message === "Session expired" ||
    message?.toLowerCase() === "unauthorized" ||
    message?.toLowerCase() === "not authenticated";

  if (isSessionExpired) {
    return (
      <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-muted-foreground/30 py-16">
        <LogIn className="h-10 w-10 text-muted-foreground/60" />
        <p className="mt-4 text-sm font-medium">Your login has expired</p>
        <p className="mt-1 max-w-sm text-center text-xs text-muted-foreground">
          Please sign in again to continue.
        </p>
        <Button variant="outline" size="sm" className="mt-4" asChild>
          <a href="/login?reason=session_expired">
            <LogIn className="mr-1.5 h-3.5 w-3.5" /> Sign in
          </a>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-destructive/30 py-16">
      <AlertCircle className="h-10 w-10 text-destructive/60" />
      <p className="mt-4 text-sm font-medium">Something went wrong</p>
      <p className="mt-1 max-w-sm text-center text-xs text-muted-foreground">
        {message ?? "Failed to load data. Check your connection and try again."}
      </p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Retry
        </Button>
      )}
    </div>
  );
}
