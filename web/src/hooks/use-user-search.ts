// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useQuery } from "@tanstack/react-query";
import { users } from "@/lib/api";

export function useUserSearch(query: string, options?: { enabled?: boolean; limit?: number }) {
	const q = query.trim();
	const limit = options?.limit ?? 10;
	return useQuery({
		queryKey: ["users", "search", q, limit],
		queryFn: () => users.search({ q, limit }),
		enabled: (options?.enabled ?? true) && q.length >= 2,
		staleTime: 30_000,
	});
}
