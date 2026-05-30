// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
const AuditLogPage = lazy(() => import("@/pages/admin/audit-log"));

export const Route = createFileRoute("/_authed/_admin/audit-log")({
  component: AuditLogPage,
});
