// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute, Outlet, useLocation } from "@tanstack/react-router";
import { lazy } from "react";

const TeamspacesPage = lazy(() => import("@/pages/registry/teamspaces"));

/**
 * `/teamspaces` is both the index and the parent of `/teamspaces/$handle`, the
 * same shape `agents/$agentId.tsx` uses: render the list at the exact path and
 * hand the child route the outlet otherwise.
 */
function TeamspacesRoute() {
	const location = useLocation();
	const currentPath = location.pathname.replace(/\/$/, "");

	if (currentPath === "/teamspaces") {
		return <TeamspacesPage />;
	}

	return <Outlet />;
}

export const Route = createFileRoute("/_authed/teamspaces")({
	component: TeamspacesRoute,
});
