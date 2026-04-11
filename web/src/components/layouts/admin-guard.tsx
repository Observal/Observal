"use client";
import { useAdminGuard } from "@/hooks/use-admin-guard";

export function AdminGuard({ children }: { children: React.ReactNode }) {
  const ready = useAdminGuard();
  if (!ready) return null;
  return <>{children}</>;
}
