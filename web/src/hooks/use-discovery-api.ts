// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { discovery } from "@/lib/api";
import type { DiscoverySearchFilter } from "@/lib/types";

const MIN_QUERY_LENGTH = 2;

/**
 * Discovery search over every registry kind at once. Disabled until the
 * query has a couple of characters; previous results are kept while a new
 * query loads so the list does not flash empty on every keystroke.
 */
export function useDiscoverySearch(text: string, filter: DiscoverySearchFilter = {}, pageSize = 10) {
	const trimmed = text.trim();
	return useQuery({
		queryKey: ["discovery", "search", trimmed, filter.kind ?? "all", filter.harness ?? "any", !!filter.includeUnapproved, pageSize],
		queryFn: () => discovery.search(trimmed, filter, pageSize),
		enabled: trimmed.length >= MIN_QUERY_LENGTH,
		placeholderData: keepPreviousData,
		staleTime: 60 * 1000,
		retry: false,
	});
}
