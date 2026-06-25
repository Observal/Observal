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


import {
  useQuery,
} from "@tanstack/react-query";
import {
  registry,
  type RegistryType,
} from "@/lib/api";

// ── Registry helpers ───────────────────────────────────────────────

export function useRegistryList(
  type: RegistryType,
  filters?: Record<string, string>,
) {
  return useQuery({
    queryKey: ["registry", type, filters],
    queryFn: () => registry.list(type, filters),
  });
}

export function useRegistryItem(type: RegistryType, id: string | undefined) {
  return useQuery({
    queryKey: ["registry", type, id],
    enabled: !!id,
    queryFn: () => registry.get(type, id!),
    staleTime: 0,
  });
}

export function useRegistryMetrics(type: RegistryType, id: string | undefined) {
  return useQuery({
    queryKey: ["registry", type, id, "metrics"],
    enabled: !!id,
    queryFn: () => registry.metrics(type, id!),
  });
}

export function useAgentVersions(agentId: string | undefined) {
  return useQuery({
    queryKey: ["agent-versions", agentId],
    enabled: !!agentId,
    queryFn: () => registry.listVersions(agentId!),
  });
}

export function useAgentVersionDetail(agentId: string | undefined, version: string | null) {
  return useQuery({
    queryKey: ["agent-version-detail", agentId, version],
    enabled: !!agentId && !!version,
    queryFn: () => registry.getVersion(agentId!, version!),
  });
}

export function useVersionDiff(
  agentId: string | undefined,
  v1: string | undefined,
  v2: string | undefined,
) {
  return useQuery({
    queryKey: ["version-diff", agentId, v1, v2],
    enabled: !!agentId && !!v1 && !!v2,
    queryFn: () => registry.getVersionDiff(agentId!, v1!, v2!),
  });
}
