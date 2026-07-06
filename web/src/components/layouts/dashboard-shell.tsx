// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { cn } from "@/lib/utils";

interface DashboardShellProps {
  children: React.ReactNode;
  className?: string;
}

export function DashboardShell({ children, className }: DashboardShellProps) {
  return (
    <div className={cn("flex min-h-0 flex-1 flex-col", className)}>
      {children}
    </div>
  );
}

export function DashboardContent({
  children,
  className,
}: DashboardShellProps) {
  return (
    <main className={cn("flex-1 overflow-y-auto p-3", className)}>
      {children}
    </main>
  );
}
