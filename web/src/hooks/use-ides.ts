// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useQuery } from "@tanstack/react-query";
import { config, type IdeEntry } from "@/lib/api";

/**
 * Fetches the canonical IDE list from the server. Cached indefinitely
 * since the IDE list rarely changes during a session.
 */
export function useIdes() {
	return useQuery<IdeEntry[]>({
		queryKey: ["config", "ides"],
		queryFn: config.ides,
		staleTime: Infinity,
		gcTime: Infinity,
	});
}
