// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0


import { useRoleGuard } from "@/hooks/use-role-guard";

/**
 * @deprecated Use `useRoleGuard("admin")` instead.
 * Kept for backward compatibility.
 */
export function useAdminGuard() {
  const { ready } = useRoleGuard("admin");
  return ready;
}
