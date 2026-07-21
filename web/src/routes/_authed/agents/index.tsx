// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
const AgentsPage = lazy(() => import("@/pages/registry/agents/index"));

export type AgentsSearch = {
  search?: string;
  namespace?: string;
  category?: string;
};

export const Route = createFileRoute("/_authed/agents/")({
  component: AgentsPage,
  validateSearch: (search: Record<string, unknown>): AgentsSearch => ({
    search: (search.search as string) || undefined,
    namespace: (search.namespace as string) || undefined,
    category: (search.category as string) || undefined,
  }),
});
