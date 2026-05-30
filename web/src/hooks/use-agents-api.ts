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
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import {
  dashboard,
  registry,
  feedback,
  bulk,
} from "@/lib/api";
import type { LeaderboardWindow } from "@/lib/types";

// ── Agent-specific ──────────────────────────────────────────────────

export function useMyAgents() {
  return useQuery({
    queryKey: ["registry", "agents", "my"],
    queryFn: () => registry.my(),
  });
}

export function useArchivedAgents(enabled = true) {
  return useQuery({
    queryKey: ["registry", "agents", "archived"],
    queryFn: () => registry.archived(),
    enabled,
  });
}

export function useAgentResolve(id: string) {
  return useQuery({
    queryKey: ["agent-resolve", id],
    queryFn: () => registry.resolve(id),
    enabled: !!id,
  });
}

export function useAgentDownloads(id: string) {
  return useQuery({
    queryKey: ["agent-downloads", id],
    queryFn: () => registry.downloads(id),
    enabled: !!id,
  });
}

export function useLeaderboard(window?: LeaderboardWindow, limit?: number, user?: string) {
  return useQuery({
    queryKey: ["leaderboard", window, limit, user],
    queryFn: () => dashboard.leaderboard(window, limit, user),
  });
}

export function useComponentLeaderboard(window?: LeaderboardWindow, limit?: number) {
  return useQuery({
    queryKey: ["component-leaderboard", window, limit],
    queryFn: () => dashboard.componentLeaderboard(window, limit),
  });
}

export function useAgentValidation() {
  return useMutation({
    mutationFn: registry.validate,
  });
}

export function useFeedbackSummary(listingId: string | undefined) {
  return useQuery({
    queryKey: ["feedback", "summary", listingId],
    enabled: !!listingId,
    queryFn: () => feedback.summary(listingId!),
  });
}
// ── Archive ────────────────────────────────────────────────────────

export function useArchiveAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.archive(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success("Agent archived");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to archive agent");
    },
  });
}

export function useUnarchiveAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.unarchive(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success("Agent restored");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to restore agent");
    },
  });
}

// ── Draft ──────────────────────────────────────────────────────────

export function useSaveDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => registry.draft(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success("Draft saved");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to save draft");
    },
  });
}

export function useUpdateDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; body: unknown }) => registry.updateDraft(vars.id, vars.body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success("Draft updated");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to update draft");
    },
  });
}

export function useUpdateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; body: unknown }) => registry.updateAgent(vars.id, vars.body),
    onSuccess: (_data: unknown, vars: { id: string; body: unknown }) => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      qc.invalidateQueries({ queryKey: ["registry", "agents", vars.id] });
      toast.success("Agent updated successfully");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to update agent");
    },
  });
}

export function useSubmitDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.submitDraft(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success("Agent submitted for review");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to submit draft");
    },
  });
}

// ── Version ────────────────────────────────────────────────────────

export function useCreateAgentVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { agentId: string; body: unknown }) =>
      registry.createVersion(vars.agentId, vars.body),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["agent-versions", vars.agentId] });
      qc.invalidateQueries({ queryKey: ["registry", "agents", vars.agentId] });
      toast.success("New version released successfully");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to release version");
    },
  });
}

export function useVersionSuggestions(id: string | undefined) {
  return useQuery({
    queryKey: ["version-suggestions", id],
    enabled: !!id,
    queryFn: () => registry.versionSuggestions(id!),
  });
}

// ── Bulk ───────────────────────────────────────────────────────────

export function useBulkCreateAgents() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: bulk.createAgents,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success(`Created ${data.created} agents`);
    },
    onError: (err: Error) => {
      toast.error(err.message || "Bulk create failed");
    },
  });
}
