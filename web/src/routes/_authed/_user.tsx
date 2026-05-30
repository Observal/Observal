// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute, Outlet } from "@tanstack/react-router";
import { RoleGuard } from "@/components/layouts/role-guard";

function UserLayout() {
  return (
    <RoleGuard minRole="user">
      <Outlet />
    </RoleGuard>
  );
}

export const Route = createFileRoute("/_authed/_user")({
  component: UserLayout,
});
