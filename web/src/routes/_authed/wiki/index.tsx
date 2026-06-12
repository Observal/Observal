// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";

const WikiPage = lazy(() => import("@/pages/wiki/index"));

export const Route = createFileRoute("/_authed/wiki/")({
	component: WikiPage,
});
