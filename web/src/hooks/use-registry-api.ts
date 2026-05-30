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
  registry,
  type RegistryType,
} from "@/lib/api";

// ── Component Draft/Submit (generic) ──────────────────────────────

export function useMyComponents(type: RegistryType) {
  return useQuery({
    queryKey: ["registry", type, "my"],
    queryFn: () => registry.my(type),
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

export function useComponentDelete(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.delete(type, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      toast.success("Deleted");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to delete");
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
