// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useQuery } from "@tanstack/react-query";
import { config } from "@/lib/api";

/**
 * Fetches the canonical harness list from the server (filtered by allowlist).
 * Also returns the configured default harness if set.
 */
export function useHarnesses() {
	const query = useQuery({
		queryKey: ["config", "harnesses"],
		queryFn: config.harnesses,
		staleTime: Infinity,
		gcTime: Infinity,
	});

	return {
		...query,
		data: query.data?.harnesses,
		defaultHarness: query.data?.default_harness ?? undefined,
	};
}
