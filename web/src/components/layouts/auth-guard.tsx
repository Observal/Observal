// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useAuthGuard, useOptionalAuth } from "@/hooks/use-auth";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { ready } = useAuthGuard();
  // Block rendering until auth state is confirmed to prevent flicker
  // of protected content before redirect
  if (!ready) return <div className="flex h-screen w-full items-center justify-center" />;
  return <>{children}</>;
}

/**
 * Allows unauthenticated browsing — renders children regardless of auth state.
 * Resolves role for authenticated users so sidebar can show/hide admin items.
 */
export function OptionalAuthGuard({ children }: { children: React.ReactNode }) {
  useOptionalAuth();
  // Render children immediately to prevent hydration mismatch
  return <>{children}</>;
}
