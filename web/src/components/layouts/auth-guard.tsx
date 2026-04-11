"use client";
import { useAuthGuard, useOptionalAuth } from "@/hooks/use-auth";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { ready } = useAuthGuard();
  if (!ready) return null;
  return <>{children}</>;
}

/**
 * Allows unauthenticated browsing — renders children regardless of auth state.
 * Resolves role for authenticated users so sidebar can show/hide admin items.
 */
export function OptionalAuthGuard({ children }: { children: React.ReactNode }) {
  const { ready } = useOptionalAuth();
  if (!ready) return null;
  return <>{children}</>;
}
