"use client";
import { useAuthGuard } from "@/hooks/use-auth";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { ready } = useAuthGuard();
  if (!ready) return null;
  return <>{children}</>;
}
