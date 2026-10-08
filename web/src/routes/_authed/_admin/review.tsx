// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
const ReviewPage = lazy(() => import("@/pages/review/queue"));

export type ReviewSearch = {
  tab?: "agents" | "components" | "teamspaces";
};

export const Route = createFileRoute("/_authed/_admin/review")({
  component: ReviewPage,
  // Inbox items deep-link to the tab holding the item they name. Without this
  // a component review always opened on the agents tab, which does not contain
  // it, and the link read as broken.
  validateSearch: (search: Record<string, unknown>): ReviewSearch => ({
    tab:
      search.tab === "components"
        ? "components"
        : search.tab === "teamspaces"
          ? "teamspaces"
          : search.tab === "agents"
            ? "agents"
            : undefined,
  }),
});
