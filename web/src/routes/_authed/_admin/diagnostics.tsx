// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
const DiagnosticsPage = lazy(() => import("@/pages/admin/diagnostics"));

export const Route = createFileRoute("/_authed/_admin/diagnostics")({
  component: DiagnosticsPage,
});
