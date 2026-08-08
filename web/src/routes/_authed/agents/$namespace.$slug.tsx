// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
import { useRegistryResolve } from "@/hooks/use-traces-api";
import { DetailSkeleton } from "@/components/shared/skeleton-layouts";
import { NotFoundState } from "@/components/shared/not-found-state";

const AgentDetail = lazy(() => import("@/pages/registry/agents/detail"));

/**
 * Canonical shareable agent URL: /agents/{namespace}/{slug}. Resolves the
 * qualified name server-side, then renders the same detail page the legacy
 * /agents/{uuid} route uses. A 404 (absent or not visible) renders the same
 * not-found state either way.
 */
function CanonicalAgentRoute() {
  const { namespace, slug } = Route.useParams();
  const resolve = useRegistryResolve("agents", `${namespace}/${slug}`);

  if (resolve.isLoading) {
    return (
      <div className="p-6 lg:p-8 w-full">
        <DetailSkeleton />
      </div>
    );
  }
  if (!resolve.data) {
    return <NotFoundState title="Agent not found" />;
  }
  return <AgentDetail agentId={resolve.data.id} />;
}

export const Route = createFileRoute("/_authed/agents/$namespace/$slug")({
  component: CanonicalAgentRoute,
});
