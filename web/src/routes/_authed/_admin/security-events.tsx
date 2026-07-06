// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
const SecurityEventsPage = lazy(() => import("@/pages/admin/security-events"));

export const Route = createFileRoute("/_authed/_admin/security-events")({
  component: SecurityEventsPage,
});
