// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { RoleGuard } from "@/components/layouts/role-guard";

/**
 * @deprecated Use `<RoleGuard minRole="admin">` instead.
 * Kept for backward compatibility.
 */
export function AdminGuard({ children }: { children: React.ReactNode }) {
  return <RoleGuard minRole="admin">{children}</RoleGuard>;
}
