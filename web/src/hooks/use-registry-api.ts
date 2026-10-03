// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
// SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: Apache-2.0


import { useEffect, useRef } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import {
  registry,
  type RegistryType,
} from "@/lib/api";
import type { McpWebhookSyncRequest } from "@/lib/types";

// ── Component Draft/Submit (generic) ──────────────────────────────

export function useMyComponents(type: RegistryType, enabled = true) {
  return useQuery({
    queryKey: ["registry", type, "my"],
    queryFn: () => registry.my(type),
    enabled,
  });
}

export function useUpdateRegistryVisibility() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ type, id, visibility }: { type: RegistryType; id: string; visibility: "public" | "team" }) =>
      registry.updateVisibility(type, id, visibility),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["registry", variables.type] });
      qc.invalidateQueries({ queryKey: ["registry", variables.type, variables.id] });
      toast.success("Visibility updated");
    },
    onError: (err: Error) => toast.error(err.message || "Failed to update visibility"),
  });
}

export function useComponentSubmit(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => registry.submit(type, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success("Submitted for review");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to submit");
    },
  });
}

export function useComponentSaveDraft(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => registry.draft(body, type),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      toast.success("Draft saved");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to save draft");
    },
  });
}

export function useComponentUpdateDraft(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; body: unknown }) =>
      registry.updateDraft(vars.id, vars.body, type),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      toast.success("Draft updated");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to update draft");
    },
  });
}

export function useComponentSubmitDraft(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.submitDraft(id, type),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success("Submitted for review");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to submit");
    },
  });
}

export function useStartEdit(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.startEdit(id, type),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review"] });
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to start editing");
    },
  });
}

export function useCancelEdit(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.cancelEdit(id, type),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review"] });
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to cancel editing");
    },
  });
}

export function useComponentArchive(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.archiveComponent(type, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      toast.success("Component archived");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to archive component");
    },
  });
}

export function useComponentUnarchive(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.unarchiveComponent(type, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      toast.success("Component restored");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to restore component");
    },
  });
}

// ── Component Versions ─────────────────────────────────────────────

export function useComponentVersions(type: RegistryType | undefined, listingId: string | undefined) {
  return useQuery({
    queryKey: ["component-versions", type, listingId],
    enabled: !!type && !!listingId,
    queryFn: () => registry.listComponentVersions(type!, listingId!),
  });
}

export function useComponentVersionDetail(type: RegistryType | undefined, listingId: string | undefined, version: string | null) {
  return useQuery({
    queryKey: ["component-version-detail", type, listingId, version],
    enabled: !!type && !!listingId && !!version,
    queryFn: () => registry.getComponentVersion(type!, listingId!, version!),
  });
}

export function usePublishComponentVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ type, listingId, body }: { type: RegistryType; listingId: string; body: unknown }) =>
      registry.publishComponentVersion(type, listingId, body),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["component-versions", variables.type, variables.listingId] });
      qc.invalidateQueries({ queryKey: ["registry", variables.type, variables.listingId] });
      toast.success("Version published successfully");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to publish version");
    },
  });
}

export function useComponentVersionSuggestions(type: RegistryType | undefined, listingId: string | undefined) {
  return useQuery({
    queryKey: ["component-version-suggestions", type, listingId],
    enabled: !!type && !!listingId,
    queryFn: () => registry.componentVersionSuggestions(type!, listingId!),
  });
}

// ── MCP GitHub webhook sync ────────────────────────────────────────

// A push can land at any time, so an open page keeps checking while sync is on.
// Polling pauses while the browser tab is hidden (TanStack Query's default).
const SYNC_WATCH_MS = 10_000;
const SYNC_RUNNING_MS = 3_000;

export function useMcpWebhookSync(listingId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["mcp-webhook-sync", listingId],
    enabled: enabled && !!listingId,
    queryFn: () => registry.mcpWebhookSync(listingId!),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data?.enabled) return false;
      return data.last_sync_status === "queued" || data.last_sync_status === "syncing"
        ? SYNC_RUNNING_MS
        : SYNC_WATCH_MS;
    },
  });
}

/** Refresh an open MCP page when a GitHub sync publishes a new version. */
export function useMcpSyncWatcher(listingId: string | undefined, enabled: boolean) {
  const qc = useQueryClient();
  const { data } = useMcpWebhookSync(listingId, enabled);
  // Version strings are unique per listing, so a new last_version means a new publish.
  const seen = useRef<string | null | undefined>(undefined);
  const lastVersion = data?.enabled ? (data.last_version ?? null) : undefined;

  useEffect(() => {
    if (lastVersion === undefined) return;
    if (seen.current === undefined) {
      seen.current = lastVersion;
      return;
    }
    if (lastVersion && lastVersion !== seen.current) {
      seen.current = lastVersion;
      qc.invalidateQueries({ queryKey: ["registry", "mcps", listingId] });
      qc.invalidateQueries({ queryKey: ["component-versions", "mcps", listingId] });
      toast.success(`Version ${lastVersion} synced from GitHub`);
    }
  }, [lastVersion, listingId, qc]);
}

function useMcpWebhookSyncMutation<TVars, TData>(
  listingId: string,
  mutationFn: (vars: TVars) => Promise<TData>,
  success: string,
  failure: string,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp-webhook-sync", listingId] });
      qc.invalidateQueries({ queryKey: ["component-versions", "mcps", listingId] });
      toast.success(success);
    },
    onError: (err: Error) => toast.error(err.message || failure),
  });
}

export function useConfigureMcpWebhookSync(listingId: string) {
  return useMcpWebhookSyncMutation(
    listingId,
    (body: McpWebhookSyncRequest) => registry.configureMcpWebhookSync(listingId, body),
    "Webhook sync saved",
    "Failed to save webhook sync",
  );
}

export function useRotateMcpWebhookSecret(listingId: string) {
  return useMcpWebhookSyncMutation(
    listingId,
    () => registry.rotateMcpWebhookSecret(listingId),
    "New secret issued. Update it in GitHub.",
    "Failed to rotate the secret",
  );
}

export function useRunMcpWebhookSync(listingId: string) {
  return useMcpWebhookSyncMutation(
    listingId,
    () => registry.runMcpWebhookSync(listingId),
    "Sync queued",
    "Failed to queue a sync",
  );
}

export function useDisableMcpWebhookSync(listingId: string) {
  return useMcpWebhookSyncMutation(
    listingId,
    () => registry.disableMcpWebhookSync(listingId),
    "Webhook sync turned off",
    "Failed to turn off webhook sync",
  );
}
