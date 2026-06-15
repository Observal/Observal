// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useQuery } from "@tanstack/react-query";
import { config } from "@/lib/api";

/**
 * Fetches the canonical IDE list from the server (filtered by allowlist).
 * Also returns the configured default IDE if set.
 */
export function useIdes() {
	const query = useQuery({
		queryKey: ["config", "ides"],
		queryFn: config.ides,
		staleTime: Infinity,
		gcTime: Infinity,
	});

	return {
		...query,
		data: query.data?.ides,
		defaultIde: query.data?.default_ide ?? undefined,
	};
}
