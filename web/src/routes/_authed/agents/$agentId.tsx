// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute, Outlet, useLocation, useParams } from "@tanstack/react-router";
import { lazy } from "react";

const AgentDetail = lazy(() => import("@/pages/registry/agents/detail"));

function AgentRoute() {
  const { agentId } = useParams({ from: "/_authed/agents/$agentId" });
  const location = useLocation();
  const agentPath = `/agents/${agentId}`;
  const currentPath = location.pathname.replace(/\/$/, "");

  if (currentPath === agentPath) {
    return <AgentDetail />;
  }

  return <Outlet />;
}

export const Route = createFileRoute("/_authed/agents/$agentId")({
  component: AgentRoute,
});
