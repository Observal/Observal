// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
// SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useEffect, useRef } from "react";
import {
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  dashboard,
} from "@/lib/api";
import type { SessionData } from "@/lib/types";

// ── Sessions ───────────────────────────────────────────────────────

export function useSessions2(options?: {
  refetchInterval?: number | false;
  platform?: string;
  days?: number;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ['sessions', 'list', options?.platform, options?.days, options?.limit, options?.offset],
    queryFn: () =>
      dashboard.sessions({
        platform: options?.platform,
        days: options?.days,
        limit: options?.limit,
        offset: options?.offset,
      }),
    refetchInterval: options?.refetchInterval,
    refetchOnMount: "always",
    staleTime: 0,
  });
}
export function useSessionsSummary() {
  return useQuery({
    queryKey: ['sessions', 'summary'],
    queryFn: dashboard.sessionsSummary,
    refetchOnMount: "always",
    staleTime: 0,
  });
}
export function useSessionDetail(id: string | undefined) {
  const qc = useQueryClient();
  const offsetRef = useRef<number | undefined>(undefined);

  // Reset offset when session changes
  useEffect(() => {
    offsetRef.current = undefined;
  }, [id]);

  return useQuery({
    queryKey: ['sessions', 'detail', id],
    queryFn: async () => {
      const data = await dashboard.session(id!, offsetRef.current);
      // Update offset cursor for next incremental fetch
      if (data && typeof (data as Record<string, unknown>).max_offset === 'number') {
        offsetRef.current = (data as Record<string, unknown>).max_offset as number;
      }
      // For incremental fetches, merge new events into existing cache
      if (offsetRef.current !== undefined && (data as Record<string, unknown>).events) {
        const existing = qc.getQueryData<SessionData>(['sessions', 'detail', id]);
        if (existing && existing.events && (data as SessionData).events.length > 0) {
          return {
            ...existing,
            events: [...existing.events, ...(data as SessionData).events],
            max_offset: (data as Record<string, unknown>).max_offset,
          } as SessionData;
        }
      }
      return data;
    },
    enabled: !!id,
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
    refetchOnMount: "always",
    staleTime: 1_000,
  });
}
export function useSessionTraces() {
  return useQuery({ queryKey: ['sessions', 'traces'], queryFn: dashboard.traces });
}
export function useSessionTrace(id: string | undefined) {
  return useQuery({ queryKey: ['sessions', 'trace', id], queryFn: () => dashboard.trace(id!), enabled: !!id });
}
export function useSessionsStats() {
  return useQuery({ queryKey: ['sessions', 'stats'], queryFn: dashboard.sessionsStats });
}
export function useSessionErrors() {
  return useQuery({ queryKey: ['sessions', 'errors'], queryFn: dashboard.sessionsErrors });
}

export function useSessionSubscription() {
  const qc = useQueryClient();
  const listDebounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    let unsubscribe: (() => void) | undefined;

    import("@/lib/graphql-ws").then(({ subscribeToSessionUpdates }) => {
      unsubscribe = subscribeToSessionUpdates((sessionId) => {
        // Debounce the list refetch (many events → one list refresh)
        clearTimeout(listDebounceRef.current);
        listDebounceRef.current = setTimeout(() => {
          qc.invalidateQueries({ queryKey: ["sessions", "list"] });
        }, 300);
        // Session detail: invalidate immediately so new turns appear
        qc.invalidateQueries({ queryKey: ["sessions", "detail", sessionId] });
      });
    });

    return () => {
      clearTimeout(listDebounceRef.current);
      unsubscribe?.();
    };
  }, [qc]);
}
