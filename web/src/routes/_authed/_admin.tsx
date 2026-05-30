// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute, Outlet } from "@tanstack/react-router";
import { RoleGuard } from "@/components/layouts/role-guard";
import { RetentionWarningBanner } from "@/components/shared/retention-warning-banner";

function AdminLayout() {
  return (
    <RoleGuard minRole="reviewer">
      <RetentionWarningBanner />
      <Outlet />
    </RoleGuard>
  );
}

export const Route = createFileRoute("/_authed/_admin")({
  component: AdminLayout,
});
