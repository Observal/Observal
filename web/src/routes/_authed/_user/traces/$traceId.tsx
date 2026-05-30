// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
const TraceDetail = lazy(() => import("@/pages/user/traces/detail"));

export const Route = createFileRoute("/_authed/_user/traces/$traceId")({
  component: TraceDetail,
});
