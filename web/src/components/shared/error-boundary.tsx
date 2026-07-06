// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-dvh items-center justify-center bg-surface-sunken p-6">
          <div className="flex flex-col items-center gap-4 text-center">
            <AlertCircle className="h-12 w-12 text-destructive/60" />
            <h1 className="text-lg font-semibold">Something went wrong</h1>
            <p className="max-w-md text-sm text-muted-foreground">
              An unexpected error occurred. Please reload the page.
            </p>
            <Button
              variant="outline"
              onClick={() => window.location.reload()}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Reload page
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
