// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useRoleGuard, type Role } from "@/hooks/use-role-guard";

export function RoleGuard({ minRole, children }: { minRole: Role; children: React.ReactNode }) {
  const { ready } = useRoleGuard(minRole);
  // Block rendering until role is confirmed to prevent flicker
  // of protected content before redirect
  if (!ready) return <div className="flex h-screen w-full items-center justify-center" />;
  return <>{children}</>;
}
