// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
const DashboardPage = lazy(() => import("@/pages/admin/dashboard/index"));

export type DashboardSearch = {
  tab?: string;
  range?: string;
};

export const Route = createFileRoute("/_authed/_admin/dashboard")({
  component: DashboardPage,
  validateSearch: (search: Record<string, unknown>): DashboardSearch => ({
    tab: (search.tab as string) || undefined,
    range: (search.range as string) || undefined,
  }),
});
