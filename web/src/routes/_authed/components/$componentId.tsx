// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
const ComponentDetail = lazy(() => import("@/pages/registry/components/detail"));

export type ComponentSearch = {
  type?: string;
};

export const Route = createFileRoute("/_authed/components/$componentId")({
  component: ComponentDetail,
  validateSearch: (search: Record<string, unknown>): ComponentSearch => ({
    type: (search.type as string) || "mcps",
  }),
});
