// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
import type { RegistryType } from "@/lib/api";
import { useRegistryResolve } from "@/hooks/use-traces-api";
import { DetailSkeleton } from "@/components/shared/skeleton-layouts";
import { NotFoundState } from "@/components/shared/not-found-state";

const ComponentDetail = lazy(() => import("@/pages/registry/components/detail"));

const COMPONENT_ROUTE_TYPES = ["mcps", "skills", "hooks", "prompts", "sandboxes"] as const;

function isComponentRouteType(value: string): value is (typeof COMPONENT_ROUTE_TYPES)[number] {
  return (COMPONENT_ROUTE_TYPES as readonly string[]).includes(value);
}

/**
 * Canonical shareable component URL: /components/{type}/{namespace}/{slug}.
 * The type lives in the path (not a query param), so a copied URL always
 * queries the right collection. Invalid types and unresolvable references
 * render the same not-found state.
 */
function CanonicalComponentRoute() {
  const { type, namespace, slug } = Route.useParams();
  const valid = isComponentRouteType(type);
  const resolve = useRegistryResolve(
    valid ? (type as RegistryType) : "mcps",
    valid ? `${namespace}/${slug}` : undefined,
  );

  if (!valid) {
    return <NotFoundState title="Component not found" />;
  }
  if (resolve.isLoading) {
    return (
      <div className="p-6 w-full">
        <DetailSkeleton />
      </div>
    );
  }
  if (!resolve.data) {
    return <NotFoundState title="Component not found" />;
  }
  return <ComponentDetail componentId={resolve.data.id} componentType={type as RegistryType} />;
}

export const Route = createFileRoute("/_authed/components/$type/$namespace/$slug")({
  component: CanonicalComponentRoute,
});
