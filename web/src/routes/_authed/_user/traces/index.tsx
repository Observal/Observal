// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Harshith Padakanti <harshaharshith31@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
const TracesPage = lazy(() => import("@/pages/user/traces/index"));

export type TracesSearch = {
  search?: string;
};

export const Route = createFileRoute("/_authed/_user/traces/")({
  component: TracesPage,
  validateSearch: (search: Record<string, unknown>): TracesSearch => ({
    search: (search.search as string) || undefined,
  }),
});
