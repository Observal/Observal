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
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import {
  registry,
  review,
  type RegistryType,
} from "@/lib/api";

// ── Review ──────────────────────────────────────────────────────────

export function useReviewList(typeFilter?: string) {
  const params = typeFilter ? { type: typeFilter } : undefined;
  return useQuery({
    queryKey: ["review", params],
    queryFn: async () => {
      const [components, agents] = await Promise.all([
        review.list(params),
        review.listAgents(),
      ]);
      return [...agents, ...components];
    },
  });
}

export function useReviewAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; type?: string; action: "approve" | "reject"; reason?: string; category?: string }) => {
      if (vars.type === "agent") {
        return vars.action === "approve"
          ? review.approveAgent(vars.id, vars.category ? { category: vars.category } : undefined)
          : review.rejectAgent(vars.id, { reason: vars.reason ?? "" });
      }
      return vars.action === "approve"
        ? review.approve(vars.id)
        : review.reject(vars.id, { reason: vars.reason ?? "" });
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success(vars.action === "approve" ? "Submission approved" : "Submission rejected");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Review action failed");
    },
  });
}
// ── Bundle Review ──────────────────────────────────────────────────

export function useBundleReviewAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; action: "approve" | "reject"; reason?: string }) =>
      vars.action === "approve"
        ? review.approveBundle(vars.id)
        : review.rejectBundle(vars.id, { reason: vars.reason ?? "" }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success(vars.action === "approve" ? "Bundle approved" : "Bundle rejected");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Bundle review action failed");
    },
  });
}

// ── Review (agents-only list) ──────────────────────────────────────

export function useReviewAgents() {
  return useQuery({
    queryKey: ["review", "agents"],
    queryFn: () => review.listAgents(),
  });
}

export function useReviewDetail(id: string | undefined) {
  return useQuery({
    queryKey: ["review", "detail", id],
    enabled: !!id,
    queryFn: () => review.get(id!),
  });
}

export function useRelatedSkills(id: string | undefined) {
  return useQuery({
    queryKey: ["review", "related-skills", id],
    enabled: !!id,
    queryFn: () => review.relatedSkills(id!).then((r) => r.skills),
  });
}

export function useApproveWithSkills() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; skillIds: string[] }) =>
      review.approveWithSkills(vars.id, { skill_ids: vars.skillIds }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success("MCP and related skills approved");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Bulk approve failed");
    },
  });
}

export function useReviewComponents(typeFilter?: string) {
  const params: Record<string, string> = { tab: "components" };
  if (typeFilter) params.type = typeFilter;
  return useQuery({
    queryKey: ["review", "components", params],
    queryFn: () => review.list(params),
  });
}

export function useReviewDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; type?: string }) => {
      const typeMap: Record<string, RegistryType> = {
        mcp: "mcps",
        skill: "skills",
        hook: "hooks",
        prompt: "prompts",
        sandbox: "sandboxes",
        agent: "agents",
      };
      const registryType = typeMap[vars.type ?? "agent"] ?? "agents";
      return registry.delete(registryType, vars.id);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success("Submission withdrawn");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to delete submission");
    },
  });
}

export function useReviewSubscription() {
  const qc = useQueryClient();
  const listDebounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    let unsubscribe: (() => void) | undefined;

    import("@/lib/graphql-ws").then(({ subscribeToReviewUpdates }) => {
      unsubscribe = subscribeToReviewUpdates(() => {
        // Debounce the list refetch (rapid approve/reject actions)
        clearTimeout(listDebounceRef.current);
        listDebounceRef.current = setTimeout(() => {
          qc.invalidateQueries({ queryKey: ["review"] });
        }, 300);
      });
    });

    return () => {
      clearTimeout(listDebounceRef.current);
      unsubscribe?.();
    };
  }, [qc]);
}
