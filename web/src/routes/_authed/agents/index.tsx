// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
const AgentsPage = lazy(() => import("@/pages/registry/agents/index"));

export type AgentsSearch = {
  search?: string;
};

export const Route = createFileRoute("/_authed/agents/")({
  component: AgentsPage,
  validateSearch: (search: Record<string, unknown>): AgentsSearch => ({
    search: (search.search as string) || undefined,
  }),
});
