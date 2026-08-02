// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
import type { RegistryType } from "@/lib/api";

const TeamspaceDetailPage = lazy(() => import("@/pages/registry/teamspace-detail"));

export type TeamspaceDetailSearch = {
	tab?: string;
	type?: RegistryType;
};

const COMPONENT_TYPES = new Set<RegistryType>(["mcps", "skills", "hooks", "prompts", "sandboxes"]);

export const Route = createFileRoute("/_authed/teamspaces/$handle")({
	component: TeamspaceDetailPage,
	validateSearch: (search: Record<string, unknown>): TeamspaceDetailSearch => ({
		tab: (search.tab as string) || undefined,
		type: COMPONENT_TYPES.has(search.type as RegistryType) ? (search.type as RegistryType) : undefined,
	}),
});
